"""The §23 EStG disposal engine (ticket 21): private Veräußerungsgeschäfte
over crypto and foreign cash, derived from the ledger — never maintained
beside it.

Disposals consume Tax Lots FIFO within their Account and Instrument (BMF
letter of 10.05.2022, wallet-based FIFO), on the same single replay the lot
engine performs, so a disposal and the lots it consumed can never disagree.
Each consumption records quantity, basis, its share of the proceeds, the
holding period and the long-term flag. Three rules sit on top:

- **Haltefrist** (§23 Abs. 1 Satz 1 Nr. 2 EStG): a period of not more than
  one year between acquisition and disposal is taxable; beyond it the
  consumption is exempt — excluded from the total, still visible in detail.
  The period runs between absolute instants and is therefore unaffected by
  timezone: one year after an instant is the same UTC timestamp one year on
  (an acquisition on 29 February completes its year on 28 February, §188
  Abs. 3 BGB analog). A confirmed self-transfer carries acquisition instants
  across (ticket 16), so it never restarts the period.
- **Freigrenze** (§23 Abs. 3 Satz 5 EStG): the per-year limit is read from
  the statutory store (ticket 09), never from a constant. A Gesamtgewinn
  below it is entirely tax-free, at or above it entirely taxable, and the
  headroom or overshoot is stated either way. A year whose limit is unset
  refuses to compute rather than assuming one.
- **Tax Year**: a disposal is bucketed by the Europe/Berlin local date of its
  instant — the same clock as every reference-rate lookup — while the
  instant itself stays absolute.

Values are stated where the ledger and the reference-rate universe can state
them (ADR-0017): the numéraire by quantity, foreign cash and pegged
stablecoins by the reference rate of the event date. A value needing a crypto
price waits for ticket 18 — such a disposal is carried explicitly as awaiting
valuation, never guessed at, and while a counted gain awaits valuation the
year states no total and no Freigrenze verdict. A consumption of a lot
acquired without consideration (a kept windfall) falls outside §23 entirely —
no Anschaffungsvorgang, per the BMF letter of 10.05.2022 — and a disposal
consuming an Opening Balance estimate is flagged as resting on one.

A disposal exceeding the lots its Account holds is a hard error naming the
shortfall — never a silent zero-basis fill.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal

from sqlalchemy import Engine, Row

from open_leprechaun.ports.reference_rates import ReferenceRateSource
from open_leprechaun.repositories import futures as futures_repository
from open_leprechaun.repositories import lots as lots_repository
from open_leprechaun.services import fx, lots
from open_leprechaun.services.stances import effective_stance, never_enters_cost_basis
from open_leprechaun.services.statutory import StatutoryValueUnsetError, required_value
from open_leprechaun.services.tax_treatment import TAX_CONSEQUENCES, Outflow

__all__ = ["LotShortfallError", "StatutoryValueUnsetError", "lot_shortfalls", "year_report"]

EXEMPTION_LIMIT_KEY = "private_sale_exemption_limit"
"""The §23 Abs. 3 Satz 5 EStG Freigrenze in the statutory vocabulary."""

_PRIVATE_SALE_FAMILIES = ("crypto", "cash")
"""The families whose disposal is a private sale — securities are capital
income (§20, ticket 46), and the numéraire never disposes at all."""

_CENT = Decimal("0.01")
"""A pro-rated share of proceeds or costs is stated in cents, the exact
remainder staying on the last consumption — no cent invented or lost."""


class LotShortfallError(Exception):
    """A disposal exceeded the lots its Account holds — the ledger is missing
    an acquisition, and filling the gap with a zero basis would silently
    overstate the gain."""


@dataclass(frozen=True)
class Consumption:
    """One lot slice a disposal consumed, FIFO within the Account and
    Instrument. `gain_eur` is None while a component awaits a valuation
    (ticket 18) — and for a slice acquired without consideration, whose
    disposal falls outside §23."""

    quantity: Decimal
    acquired_at: datetime
    holding_days: int
    # Held beyond the Haltefrist: exempt, excluded from the total, and still
    # stated in full here.
    long_term: bool
    basis_eur: Decimal | None
    basis_source: str
    proceeds_eur: Decimal | None
    gain_eur: Decimal | None


@dataclass(frozen=True)
class Disposal:
    """One disposal leg with everything it consumed. `proceeds_eur` and
    `costs_eur` are None while they await a valuation no rate can state."""

    leg_id: int
    account_id: int
    instrument_id: int
    disposed_at: datetime
    tax_year: int
    quantity: Decimal
    proceeds_eur: Decimal | None
    # The fees charged against this leg (ADR-0011): the disposal's own costs,
    # never part of any basis.
    costs_eur: Decimal | None
    # Whether a consumed lot rests on an Opening Balance's declared estimate,
    # so a report can say which figures rest on an assumption.
    rests_on_estimate: bool
    # The dust-sweep Aggregate the disposing Transaction belongs to (ticket
    # 30): the marker the summary presentation collapses on. The disposal
    # itself stays in every total — an Aggregate suppresses nothing.
    aggregate_id: int | None
    consumptions: tuple[Consumption, ...]


@dataclass(frozen=True)
class FreigrenzeVerdict:
    """The §23 Abs. 3 Satz 5 EStG all-or-nothing answer for one year: below
    the limit the whole Gesamtgewinn is free and the headroom is stated; at
    or above it the whole amount is taxable and the overshoot is stated."""

    limit_eur: Decimal
    total_gain_eur: Decimal
    tax_free: bool
    headroom_eur: Decimal | None
    overshoot_eur: Decimal | None
    taxable_gain_eur: Decimal


@dataclass(frozen=True)
class Section23Year:
    """Every private sale of one Tax Year, exempt ones included — the total
    and the verdict cover only what counts. While a counted gain awaits
    valuation the year states no total and no verdict, and names the
    disposals it waits on."""

    year: int
    disposals: tuple[Disposal, ...]
    total_gain_eur: Decimal | None
    awaiting_valuation: tuple[int, ...]
    freigrenze: FreigrenzeVerdict | None


def year_report(engine: Engine, source: ReferenceRateSource, *, year: int) -> Section23Year:
    """The §23 answer for one Tax Year, derived from the beginning of time —
    FIFO has no shorter memory."""
    limit = required_value(
        engine, year=year, key=EXEMPTION_LIMIT_KEY, statute="§23 Abs. 3 Satz 5 EStG"
    )
    replay = _replay(engine)
    instruments = replay.instruments

    disposals = []
    for transaction, leg, consumed in _private_sales(replay):
        siblings = replay.legs_of.get(transaction.id, [])
        # Whatever year the gap sits in: every later consumption's FIFO
        # position rests on it, so no year computes over it.
        _refuse_shortfall(leg, consumed, transaction, instruments)
        # Only the requested year is valued: another year's disposal must
        # not cost a rate lookup here — nor fail over one.
        if fx.event_date(transaction.occurred_at).year != year:
            continue
        disposals.append(
            _disposal(engine, source, transaction, leg, siblings, consumed, instruments)
        )

    awaiting = tuple(
        disposal.leg_id
        for disposal in disposals
        if any(_counts(piece) and piece.gain_eur is None for piece in disposal.consumptions)
    )
    total = (
        sum(
            (
                piece.gain_eur
                for disposal in disposals
                for piece in disposal.consumptions
                if _counts(piece) and piece.gain_eur is not None
            ),
            Decimal(0),
        )
        if not awaiting
        else None
    )
    return Section23Year(
        year=year,
        disposals=tuple(disposals),
        total_gain_eur=total,
        awaiting_valuation=awaiting,
        freigrenze=_verdict(limit, total) if total is not None else None,
    )


def lot_shortfalls(engine: Engine, *, through_year: int) -> list[str]:
    """One Instrument symbol per disposal up to the end of the Tax Year that
    exceeds the lots its Account holds — the same judgement year_report
    refuses over (LotShortfallError), enumerated in full so the pre-flight
    (ticket 25) can name every gap instead of failing on the first."""
    replay = _replay(engine)
    return [
        replay.instruments[leg.instrument_id].symbol
        for transaction, leg, consumed in _private_sales(replay)
        if fx.event_date(transaction.occurred_at).year <= through_year
        and sum((piece.quantity for piece in consumed), Decimal(0)) < leg.quantity
    ]


@dataclass(frozen=True)
class _Replay:
    """One full replay of the ledger with the indexes the disposal walks
    need, so year_report and lot_shortfalls judge the very same pairing."""

    transaction_rows: list[Row]
    legs_of: dict[int, list[Row]]
    instruments: dict[int, Row]
    decisions_of: dict[int, list[Row]]
    consumed: dict[int, list[lots.Slice]]


def _replay(engine: Engine) -> _Replay:
    with lots.snapshot(engine) as connection:
        transaction_rows, leg_rows = lots_repository.ledger(connection)
        numeraire = lots_repository.numeraire_instruments(connection)
        stance_rows = lots_repository.stance_rows(connection)
        match_rows = lots_repository.match_rows(connection)
        instrument_rows = lots_repository.instrument_rows(connection)
        futures_close_rows = futures_repository.closed_position_rows(connection)
    derived = lots.derive(
        transaction_rows,
        leg_rows,
        numeraire_instruments=numeraire,
        stance_rows=stance_rows,
        match_rows=match_rows,
        futures_close_rows=futures_close_rows,
    )
    return _Replay(
        transaction_rows=transaction_rows,
        legs_of=lots.grouped(leg_rows, "transaction_id"),
        instruments={row.id: row for row in instrument_rows},
        decisions_of=lots.grouped(stance_rows, "instrument_id"),
        consumed=derived.consumed,
    )


def _private_sales(replay: _Replay) -> Iterator[tuple[Row, Row, list[lots.Slice]]]:
    """Every §23 disposal leg of the whole ledger with what it consumed —
    (transaction, out-leg, consumed slices), in ledger order."""
    for transaction in replay.transaction_rows:
        if TAX_CONSEQUENCES[transaction.type].outflow is not Outflow.disposal:
            continue
        for leg in replay.legs_of.get(transaction.id, []):
            if leg.role != "out" or not _is_private_sale(
                leg, replay.instruments, replay.decisions_of
            ):
                continue
            yield transaction, leg, replay.consumed.get(leg.id, [])


def _is_private_sale(
    leg: Row, instruments: dict[int, Row], decisions_of: dict[int, list[Row]]
) -> bool:
    """Whether this out-leg is a §23 event at all: a non-numéraire crypto or
    cash Instrument not standing ignored or dangerous at this Account — the
    same rule that blocks a mint (services/lots), because such a position
    never entered the cost basis and stays a ledger entry, never quietly a
    sale. An unacknowledged one participates: its Account may hold carried
    lots (a confirmed transfer needs no separate keep), and where nothing
    minted, the shortfall error asks for the classification loudly rather
    than dropping a sale."""
    instrument = instruments[leg.instrument_id]
    if instrument.is_numeraire or instrument.family not in _PRIVATE_SALE_FAMILIES:
        return False
    stance = effective_stance(decisions_of.get(leg.instrument_id, ()), leg.account_id)
    return not never_enters_cost_basis(stance)


def _refuse_shortfall(
    leg: Row, consumed: list[lots.Slice], transaction: Row, instruments: dict[int, Row]
) -> None:
    held = sum((piece.quantity for piece in consumed), Decimal(0))
    if held >= leg.quantity:
        return
    symbol = instruments[leg.instrument_id].symbol
    raise LotShortfallError(
        f"The disposal of {leg.quantity} {symbol}"
        f" on {transaction.occurred_at.astimezone(UTC).isoformat()}"
        f" exceeds the lots its Account holds by {leg.quantity - held} {symbol} —"
        " an acquisition is missing from the ledger."
    )


def _disposal(
    engine: Engine,
    source: ReferenceRateSource,
    transaction: Row,
    leg: Row,
    siblings: list[Row],
    consumed: list[lots.Slice],
    instruments: dict[int, Row],
) -> Disposal:
    at = transaction.occurred_at
    proceeds = _proceeds(engine, source, transaction, leg, siblings, instruments)
    costs = _costs(engine, source, leg, siblings, instruments, at)
    proceeds_shares = _shares(proceeds, consumed, leg.quantity)
    costs_shares = _shares(costs, consumed, leg.quantity)
    instrument = instruments[leg.instrument_id]
    consumptions = tuple(
        _consumption(
            piece,
            at,
            proceeds_share,
            costs_share,
            _basis(engine, source, piece, instrument, at),
        )
        for piece, proceeds_share, costs_share in zip(
            consumed, proceeds_shares, costs_shares, strict=True
        )
    )
    return Disposal(
        leg_id=leg.id,
        account_id=leg.account_id,
        instrument_id=leg.instrument_id,
        disposed_at=at,
        tax_year=fx.event_date(at).year,
        quantity=leg.quantity,
        proceeds_eur=proceeds,
        costs_eur=costs,
        rests_on_estimate=any(piece.basis_source == lots.ESTIMATE for piece in consumed),
        aggregate_id=transaction.aggregate_id,
        consumptions=consumptions,
    )


def _basis(
    engine: Engine,
    source: ReferenceRateSource,
    piece: lots.Slice,
    instrument: Row,
    disposed_at: datetime,
) -> Decimal | None:
    """The consumed slice's basis. A lot minted by §22 income (ticket 22)
    stores no basis until the rate tickets extend the derivation; its basis
    is the market value on receipt, stated here by the same rule — and at the
    same instant — that valued the income, so income and cost basis can never
    disagree. Only a slice that counts is valued: a Haltefrist-exempt one is
    excluded from the total, so it must not cost a rate lookup at its old
    acquisition date — nor crash the year over one it cannot move."""
    if (
        piece.basis_eur is None
        and piece.basis_source == lots.MARKET_VALUE
        and disposed_at <= _one_year_after(piece.acquired_at)
    ):
        return fx.value_eur(
            engine, source, instrument=instrument, quantity=piece.quantity, at=piece.acquired_at
        )
    return piece.basis_eur


def _consumption(
    piece: lots.Slice,
    disposed_at: datetime,
    proceeds_share: Decimal | None,
    costs_share: Decimal | None,
    basis_eur: Decimal | None,
) -> Consumption:
    if piece.basis_source == lots.WITHOUT_CONSIDERATION:
        # No Anschaffungsvorgang (BMF letter of 10.05.2022): the disposal
        # falls outside §23 — no gain exists to state.
        gain = None
    elif proceeds_share is None or costs_share is None or basis_eur is None:
        gain = None
    else:
        gain = proceeds_share - basis_eur - costs_share
    return Consumption(
        quantity=piece.quantity,
        acquired_at=piece.acquired_at,
        holding_days=(disposed_at - piece.acquired_at).days,
        long_term=disposed_at > _one_year_after(piece.acquired_at),
        basis_eur=basis_eur,
        basis_source=piece.basis_source,
        proceeds_eur=proceeds_share,
        gain_eur=gain,
    )


def _counts(piece: Consumption) -> bool:
    """Whether this consumption enters the Gesamtgewinn: exempt long-term
    holdings and acquisitions without consideration stay visible in detail
    but never in the total."""
    return not piece.long_term and piece.basis_source != lots.WITHOUT_CONSIDERATION


def _one_year_after(acquired_at: datetime) -> datetime:
    """The instant the Haltefrist completes: the same UTC timestamp one year
    on — held exactly one year is still 'nicht mehr als ein Jahr', taxable;
    only beyond it is the disposal exempt. An acquisition on 29 February
    completes on 28 February (§188 Abs. 3 BGB analog)."""
    at = acquired_at.astimezone(UTC)
    try:
        return at.replace(year=at.year + 1)
    except ValueError:
        return at.replace(year=at.year + 1, day=28)


def _proceeds(
    engine: Engine,
    source: ReferenceRateSource,
    transaction: Row,
    leg: Row,
    siblings: list[Row],
    instruments: dict[int, Row],
) -> Decimal | None:
    """The Veräußerungspreis: the value of the consideration received. A
    spend's consideration left the ledger, so what was given values it; a
    trade's is what arrived. Splitting one consideration across several
    out-legs needs their relative market values — None, never a guess."""
    at = transaction.occurred_at
    if transaction.type == "spend":
        return fx.value_eur(
            engine, source, instrument=instruments[leg.instrument_id], quantity=leg.quantity, at=at
        )
    if sum(sibling.role == "out" for sibling in siblings) > 1:
        return None
    total = Decimal(0)
    for sibling in siblings:
        if sibling.role != "in":
            continue
        value = fx.value_eur(
            engine,
            source,
            instrument=instruments[sibling.instrument_id],
            quantity=sibling.quantity,
            at=at,
        )
        if value is None:
            return None
        total += value
    return total


def _costs(
    engine: Engine,
    source: ReferenceRateSource,
    leg: Row,
    siblings: list[Row],
    instruments: dict[int, Row],
    at: datetime,
) -> Decimal | None:
    """The disposal's own costs: the fees charged against this leg
    (ADR-0011). A fee no rate can value leaves the costs None — awaiting
    valuation, never omitted as if it were zero."""
    total = Decimal(0)
    for sibling in siblings:
        if sibling.role != "fee" or sibling.charged_against_leg_id != leg.id:
            continue
        value = fx.value_eur(
            engine,
            source,
            instrument=instruments[sibling.instrument_id],
            quantity=sibling.quantity,
            at=at,
        )
        if value is None:
            return None
        total += value
    return total


def _shares(
    total: Decimal | None, consumed: list[lots.Slice], quantity: Decimal
) -> list[Decimal | None]:
    """One disposal-level amount pro-rated over its consumptions by quantity:
    every share but the last stated in cents, the exact remainder on the last
    — no cent invented or lost."""
    if total is None or not consumed:
        return [None] * len(consumed)
    shares: list[Decimal | None] = []
    allocated = Decimal(0)
    for piece in consumed[:-1]:
        share = (total * piece.quantity / quantity).quantize(_CENT, ROUND_HALF_EVEN)
        shares.append(share)
        allocated += share
    shares.append(total - allocated)
    return shares


def _verdict(limit: Decimal, total: Decimal) -> FreigrenzeVerdict:
    tax_free = total < limit
    return FreigrenzeVerdict(
        limit_eur=limit,
        total_gain_eur=total,
        tax_free=tax_free,
        headroom_eur=limit - total if tax_free else None,
        overshoot_eur=total - limit if not tax_free else None,
        taxable_gain_eur=Decimal(0) if tax_free else total,
    )
