"""The Holdings view (ticket 20): one portfolio of everything held — crypto
and cash — assembled on one snapshot of the ledger.

Quantity is what the ledger holds: in-legs minus out- and fee-legs per
(Account, Instrument), whatever the stance — an ignored or dangerous position
stays visible, marked, never hidden. The cost basis is read from the Tax Lot
derivation's remaining queues (ADR-0014), never summed from inflows, so the
portfolio and the tax report cannot disagree; where the lots cannot state it
— a valuation still awaited, or quantity no lot ever vouched for — the basis
says so instead of summing what it knows as if the rest were zero.

Values are stated only where the store can state them: the numéraire by
identity, foreign cash and pegged stablecoins by the latest stored reference
rate within the publication lookback (ADR-0017), crypto by the last known
stored price with its source and age (ADR-0018). The request path performs no
outside I/O at all — no price provider and no rate fetch; conversions made
elsewhere (the tax engines, the display-rate endpoint) keep the rate store
warm — which is what keeps the view inside its one-second budget by
construction. A position nothing stored can value is marked unpriced and
excluded from totals, never a zero.

The DisplayCurrency (ticket 20) is presentation only: every figure here is
EUR, and the display rate is served beside them for the client to multiply —
no tax figure ever passes through it.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

from sqlalchemy import Engine, Row

from open_leprechaun.ports.reference_rates import ReferenceRateSource
from open_leprechaun.repositories import futures as futures_repository
from open_leprechaun.repositories import holdings as holdings_repository
from open_leprechaun.repositories import lots as lots_repository
from open_leprechaun.repositories import reference_rates
from open_leprechaun.services import futures as futures_service
from open_leprechaun.services import fx, lots
from open_leprechaun.services.fx import ConvertedAmount, RateUnavailableError
from open_leprechaun.services.stances import effective_stance, never_enters_cost_basis

__all__ = ["Position", "RateUnavailableError", "display_rate", "portfolio"]

AWAITING_VALUATION = "awaiting_valuation"
"""The basis gap of a position whose remaining lots await a market value —
the same admission the disposal engine (21) carries, never a zero."""

UNVOUCHED = "unvouched"
"""The basis gap of a position holding quantity no lot ever vouched for — an
unmatched transfer in, or an inflow minted nothing — so a stated basis would
cover less than the position holds."""

_CENT = Decimal("0.01")
"""Derived money — a value, an unrealised result, an average — is stated in
cents; a basis is passed through as the lots state it."""

_FINE = Decimal("1E-8")
"""An average cost below one euro keeps eight fraction digits — a cent would
round a micro-priced token's whole answer away."""


@dataclass(frozen=True)
class Position:
    """One (Account, Instrument) holding. `marker` names why a position is
    excluded from totals — dangerous, ignored, unacknowledged or unpriced —
    and None means it counts. `basis_gap` names why the basis cannot be
    stated while the position itself still counts."""

    instrument_id: int
    symbol: str
    name: str
    family: str
    type: str
    chain: str | None
    contract_address: str | None
    isin: str | None
    is_numeraire: bool
    account_id: int
    account_name: str
    access_software: str | None
    platform_name: str
    platform_kind: str
    quantity: Decimal
    marker: str | None
    basis_eur: Decimal | None
    basis_gap: str | None
    average_cost_eur: Decimal | None
    value_eur: Decimal | None
    unrealised_eur: Decimal | None
    price_source: str | None
    price_as_of: datetime | None
    rate_date: date | None


def portfolio(engine: Engine) -> list[Position]:
    """Everything held right now, one Position per (Account, Instrument) with
    quantity on the books — derived and read on one snapshot, then valued
    from the store. Deliberately takes no rate source: the request path
    cannot fetch, so it cannot block on anyone else's availability."""
    with lots.snapshot(engine) as connection:
        transaction_rows, leg_rows = lots_repository.ledger(connection)
        numeraire = lots_repository.numeraire_instruments(connection)
        stance_rows = lots_repository.stance_rows(connection)
        match_rows = lots_repository.match_rows(connection)
        instrument_rows = lots_repository.instrument_rows(connection)
        account_rows = holdings_repository.account_rows(connection)
        price_rows = holdings_repository.price_rows(connection)
        futures_close_rows = futures_repository.closed_position_rows(connection)
    derived = lots.derive(
        transaction_rows,
        leg_rows,
        numeraire_instruments=numeraire,
        stance_rows=stance_rows,
        match_rows=match_rows,
        futures_close_rows=futures_close_rows,
    )
    instruments = {row.id: row for row in instrument_rows}
    accounts = {row.id: row for row in account_rows}
    prices = {row.instrument_id: row for row in price_rows}
    decisions_of = lots.grouped(stance_rows, "instrument_id")

    positions = []
    for (account_id, instrument_id), quantity in sorted(
        _held(leg_rows, futures_close_rows).items()
    ):
        if quantity == 0:
            continue
        instrument = instruments[instrument_id]
        # The numéraire is acknowledged by designation — it waits in no inbox
        # and nobody records a stance on it.
        stance = (
            "kept"
            if instrument.is_numeraire
            else effective_stance(decisions_of.get(instrument_id, ()), account_id)
        )
        basis, gap = _basis(
            instrument,
            stance,
            quantity,
            derived.remaining.get((account_id, instrument_id), []),
        )
        valuation = _valuation(engine, instrument, quantity, prices.get(instrument_id))
        positions.append(
            _position(
                instrument,
                accounts[account_id],
                quantity,
                stance=stance,
                basis=basis,
                gap=gap,
                valuation=valuation,
            )
        )
    positions.sort(key=lambda entry: (entry.symbol, entry.instrument_id, entry.account_id))
    return positions


def display_rate(engine: Engine, source: ReferenceRateSource, *, currency: str) -> ConvertedAmount:
    """The most recent published rate for a DisplayCurrency — units per euro,
    with the date it represents. Presentation only: the client multiplies EUR
    figures by it for display, and no tax figure ever passes through it.
    Raises RateUnavailableError for a currency the reference-rate universe
    does not cover."""
    return fx.convert(engine, source, amount=Decimal(1), currency=currency, at=datetime.now(UTC))


@dataclass(frozen=True)
class _Valuation:
    """What the store can state a position to be worth, and on whose word."""

    value_eur: Decimal | None
    price_source: str | None
    price_as_of: datetime | None
    rate_date: date | None


_UNVALUED = _Valuation(None, None, None, None)


def _held(leg_rows: list[Row], futures_close_rows: list[Row]) -> dict[tuple[int, int], Decimal]:
    """What the books say sits where: in-legs minus out- and fee-legs, per
    (Account, Instrument) — plus what coin-margined closes settled
    (ticket 29), the same positive net figures whose lots the derivation
    mints, so quantity and queue can never disagree. A losing close reduces
    nothing here: it consumed no lot, and the drift it leaves at the venue
    is reconciliation's to surface (ticket 39)."""
    held: dict[tuple[int, int], Decimal] = {}
    for leg in leg_rows:
        key = (leg.account_id, leg.instrument_id)
        signed = leg.quantity if leg.role == "in" else -leg.quantity
        held[key] = held.get(key, Decimal(0)) + signed
    for close in futures_close_rows:
        net = futures_service.net_figure(close)
        if net <= 0:
            continue
        key = (close.account_id, close.settlement_instrument_id)
        held[key] = held.get(key, Decimal(0)) + net
    return held


def _basis(
    instrument: Row, stance: str, quantity: Decimal, remaining: list[lots.Slice]
) -> tuple[Decimal | None, str | None]:
    """What the remaining lots state the position cost, or why they cannot.

    The numéraire has no basis — every basis is expressed in it. An ignored
    or dangerous position deliberately never entered the cost basis
    (ADR-0012): no basis and no gap, the marker explains. Anything else is
    judged against its queue: quantity the lots do not cover is unvouched,
    a slice still awaiting its valuation leaves the whole basis awaited —
    stated as such, never summed short.
    """
    if instrument.is_numeraire or never_enters_cost_basis(stance):
        return None, None
    if sum((piece.quantity for piece in remaining), Decimal(0)) != quantity:
        return None, UNVOUCHED
    if any(piece.basis_eur is None for piece in remaining):
        return None, AWAITING_VALUATION
    return sum((piece.basis_eur for piece in remaining), Decimal(0)), None


def _valuation(engine: Engine, instrument: Row, quantity: Decimal, price: Row | None) -> _Valuation:
    """The one valuation routing of ADR-0017 and ADR-0018, answered from the
    store alone: the numéraire by identity, foreign cash and pegged
    stablecoins by the latest stored reference rate within the publication
    lookback — never a fetch, so a quiet morning or a source outage cannot
    block the view — and crypto by the last known stored price. What nothing
    stored can value stays None, never a guess."""
    if instrument.is_numeraire:
        return _Valuation(_cents(quantity), None, None, None)
    currency = fx.valuation_currency(instrument)
    if currency == "EUR":
        # A euro stablecoin pegs to the numéraire itself — identity, no rate.
        return _Valuation(
            _cents(quantity), "reference_rate", None, fx.event_date(datetime.now(UTC))
        )
    if currency is not None:
        on = fx.event_date(datetime.now(UTC))
        floor = on - timedelta(days=fx.PUBLICATION_LOOKBACK_DAYS)
        row = reference_rates.latest_on_or_before(engine, currency=currency, on=on, floor=floor)
        if row is None:
            return _UNVALUED
        return _Valuation(_cents(quantity / row.rate), "reference_rate", None, row.rate_date)
    if instrument.family == "crypto" and price is not None:
        return _Valuation(_cents(quantity * price.price_eur), price.source, price.as_of, None)
    return _UNVALUED


def _position(
    instrument: Row,
    account: Row,
    quantity: Decimal,
    *,
    stance: str,
    basis: Decimal | None,
    gap: str | None,
    valuation: _Valuation,
) -> Position:
    if stance in ("dangerous", "ignored", "unacknowledged"):
        marker = stance
    elif valuation.value_eur is None:
        marker = "unpriced"
    else:
        marker = None
    unrealised = (
        valuation.value_eur - basis
        if valuation.value_eur is not None and basis is not None
        else None
    )
    return Position(
        instrument_id=instrument.id,
        symbol=instrument.symbol,
        name=instrument.name,
        family=instrument.family,
        type=instrument.type,
        chain=instrument.chain,
        contract_address=instrument.contract_address,
        isin=instrument.isin,
        is_numeraire=instrument.is_numeraire,
        account_id=account.id,
        account_name=account.name,
        access_software=account.access_software,
        platform_name=account.platform_name,
        platform_kind=account.platform_kind,
        quantity=quantity,
        marker=marker,
        basis_eur=basis,
        basis_gap=gap,
        average_cost_eur=_average(basis, quantity),
        value_eur=valuation.value_eur,
        unrealised_eur=unrealised,
        price_source=valuation.price_source,
        price_as_of=valuation.price_as_of,
        rate_date=valuation.rate_date,
    )


def _average(basis: Decimal | None, quantity: Decimal) -> Decimal | None:
    if basis is None or quantity == 0:
        return None
    average = basis / quantity
    fine = average != 0 and abs(average) < 1
    return average.quantize(_FINE if fine else _CENT, ROUND_HALF_EVEN)


def _cents(amount: Decimal) -> Decimal:
    return amount.quantize(_CENT, ROUND_HALF_EVEN)
