"""What every disposal engine walks (tickets 21, 46): one full replay of the
ledger with the indexes a disposal read needs, the disposal legs of a family
set paired with what they consumed, the valuation of proceeds and of a
disposal's own costs, the pro-rating of a disposal-level amount over its
consumptions, and the refusal of a disposal no lots vouch for.

The regimes stay in their own modules — §23's Haltefrist and Freigrenze in
services/section23, §20's categories and Teilfreistellung in
services/security_disposals. What lives here is regime-blind: FIFO pairing is
the lot engine's single replay, a Veräußerungspreis is the value of the
consideration received whatever the statute, and a missing acquisition is a
ledger gap however the gain would have been taxed.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Engine, Row

from open_leprechaun.ports.reference_rates import ReferenceRateSource
from open_leprechaun.repositories import futures as futures_repository
from open_leprechaun.repositories import lots as lots_repository
from open_leprechaun.services import fx, lots
from open_leprechaun.services.rounding import cents
from open_leprechaun.services.stances import effective_stance, never_enters_cost_basis
from open_leprechaun.services.tax_treatment import TAX_CONSEQUENCES, Outflow

__all__ = [
    "LOT_CONSUMING_FAMILIES",
    "LotShortfallError",
    "Replay",
    "costs",
    "lot_shortfalls",
    "proceeds",
    "prorated",
    "refuse_shortfall",
    "replay",
    "sales",
    "valued_sum",
]

LOT_CONSUMING_FAMILIES = ("crypto", "cash", "security")
"""Every family whose disposal consumes Tax Lots — which regime the gain
falls under is the Instrument's family's answer (§23 for crypto and foreign
cash, §20 for securities), but a disposal exceeding its lots is the same
missing acquisition in all of them."""


class LotShortfallError(Exception):
    """A disposal exceeded the lots its Account holds — the ledger is missing
    an acquisition, and filling the gap with a zero basis would silently
    overstate the gain."""


@dataclass(frozen=True)
class Replay:
    """One full replay of the ledger with the indexes the disposal walks
    need, so every engine — and the pre-flight — judges the very same
    pairing."""

    transaction_rows: list[Row]
    legs_of: dict[int, list[Row]]
    leg_by_id: dict[int, Row]
    instruments: dict[int, Row]
    decisions_of: dict[int, list[Row]]
    consumed: dict[int, list[lots.Slice]]


def replay(engine: Engine) -> Replay:
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
    return Replay(
        transaction_rows=transaction_rows,
        legs_of=lots.grouped(leg_rows, "transaction_id"),
        leg_by_id={leg.id: leg for leg in leg_rows},
        instruments={row.id: row for row in instrument_rows},
        decisions_of=lots.grouped(stance_rows, "instrument_id"),
        consumed=derived.consumed,
    )


def sales(
    walked: Replay, *, families: tuple[str, ...]
) -> Iterator[tuple[Row, Row, list[lots.Slice]]]:
    """Every disposal leg of the given families with what it consumed —
    (transaction, out-leg, consumed slices), in ledger order. The numéraire
    never disposes, and an Instrument standing ignored or dangerous at its
    Account never entered the cost basis (ADR-0012) — its leg stays a ledger
    entry, never quietly a sale. An unacknowledged one participates: its
    Account may hold carried lots (a confirmed transfer needs no separate
    keep), and where nothing minted, the shortfall error asks for the
    classification loudly rather than dropping a sale."""
    for transaction in walked.transaction_rows:
        if TAX_CONSEQUENCES[transaction.type].outflow is not Outflow.disposal:
            continue
        for leg in walked.legs_of.get(transaction.id, []):
            if leg.role != "out":
                continue
            instrument = walked.instruments[leg.instrument_id]
            if instrument.is_numeraire or instrument.family not in families:
                continue
            stance = effective_stance(
                walked.decisions_of.get(leg.instrument_id, ()), leg.account_id
            )
            if never_enters_cost_basis(stance):
                continue
            yield transaction, leg, walked.consumed.get(leg.id, [])


def refuse_shortfall(
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


def lot_shortfalls(engine: Engine, *, through_year: int) -> list[str]:
    """One Instrument symbol per disposal up to the end of the Tax Year that
    exceeds the lots its Account holds — the same judgement the engines
    refuse over (LotShortfallError), enumerated in full over every
    lot-consuming family so the pre-flight (ticket 25) can name every gap
    instead of failing on the first."""
    walked = replay(engine)
    return [
        walked.instruments[leg.instrument_id].symbol
        for transaction, leg, consumed in sales(walked, families=LOT_CONSUMING_FAMILIES)
        if fx.event_date(transaction.occurred_at).year <= through_year
        and sum((piece.quantity for piece in consumed), Decimal(0)) < leg.quantity
    ]


def valued_sum(
    engine: Engine,
    source: ReferenceRateSource,
    legs: list[Row],
    instruments: dict[int, Row],
    at: datetime,
) -> Decimal | None:
    """The legs' EUR value at one instant, summed — None as soon as one has
    no value the rate universe can state: awaiting valuation, never a member
    silently omitted as if it were zero."""
    total = Decimal(0)
    for leg in legs:
        value = fx.value_eur(
            engine,
            source,
            instrument=instruments[leg.instrument_id],
            quantity=leg.quantity,
            at=at,
        )
        if value is None:
            return None
        total += value
    return total


def proceeds(
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
    return valued_sum(engine, source, [s for s in siblings if s.role == "in"], instruments, at)


def costs(
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
    return valued_sum(
        engine,
        source,
        [s for s in siblings if s.role == "fee" and s.charged_against_leg_id == leg.id],
        instruments,
        at,
    )


def prorated(
    total: Decimal | None, consumed: list[lots.Slice], quantity: Decimal
) -> list[Decimal | None]:
    """One disposal-level amount pro-rated over its consumptions by quantity:
    every share but the last stated in cents (services/rounding), the exact
    remainder on the last — no cent invented or lost."""
    if total is None or not consumed:
        return [None] * len(consumed)
    result: list[Decimal | None] = []
    allocated = Decimal(0)
    for piece in consumed[:-1]:
        share = cents(total * piece.quantity / quantity)
        result.append(share)
        allocated += share
    result.append(total - allocated)
    return result
