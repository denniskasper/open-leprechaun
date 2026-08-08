"""Self-transfer matching (ticket 16): moving assets between the Admin's own
Accounts must not look like a sale and a fresh purchase. The app proposes
candidate pairs — an out-leg of a `transfer_out` and an in-leg of a
`transfer_in`, same Instrument, quantity within a fee tolerance, inside a
time window — and the Admin confirms or rejects each one. Nothing links
itself: a candidate is derived, never stored, and only a decision is a row.

A confirmed link is what lets the lot engine (services/lots.py) carry the
original cost basis and acquisition date across, so a self-transfer does not
restart the Haltefrist and a Depotübertrag preserves lot identity. An
unmatched transfer stays visible as unmatched — never quietly a disposal.

Confirming is judged looser than proposing: the tolerance and window are
proposal heuristics, but the Admin may know that a slow chain or an odd fee
put a genuine self-transfer outside them, so a confirmation is refused only
for what cannot be a self-transfer at all — wrong shapes, mixed Instruments,
one Account, or more arriving than left.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol

from sqlalchemy import Engine

from open_leprechaun.repositories import transfer_matches

QUANTITY_TOLERANCE = Decimal("0.01")
"""How much of what left may have been consumed en route — a network or
withdrawal fee — for the pair to still be proposed: one percent."""

TIME_WINDOW = timedelta(hours=72)
"""How far apart the two sides may be recorded and still be proposed. Venue
clocks disagree and chains congest, so the window is generous and symmetric
rather than assuming the deposit was stamped after the withdrawal."""


class TransferSide(Protocol):
    """One side of a possible self-transfer — a repository row or anything
    shaped like one."""

    @property
    def instrument_id(self) -> int: ...

    @property
    def account_id(self) -> int: ...

    @property
    def quantity(self) -> Decimal: ...

    @property
    def occurred_at(self) -> datetime: ...


def is_candidate(outgoing: TransferSide, incoming: TransferSide) -> bool:
    """Whether a withdrawal and a deposit look like one self-transfer: the
    same Instrument moving between two different Accounts, no more arriving
    than left, what is missing within the fee tolerance, and the two instants
    within the time window."""
    if outgoing.instrument_id != incoming.instrument_id:
        return False
    if outgoing.account_id == incoming.account_id:
        return False
    if incoming.quantity > outgoing.quantity:
        return False
    if outgoing.quantity - incoming.quantity > outgoing.quantity * QUANTITY_TOLERANCE:
        return False
    return abs(incoming.occurred_at - outgoing.occurred_at) <= TIME_WINDOW


class LegShape(Protocol):
    """What judging a proposed pair needs to know about one leg — a
    `repositories.transfer_matches.leg_details` row or anything shaped so."""

    @property
    def role(self) -> str: ...

    @property
    def type(self) -> str: ...

    @property
    def quantity(self) -> Decimal: ...

    @property
    def account_id(self) -> int: ...

    @property
    def instrument_id(self) -> int: ...

    @property
    def is_numeraire(self) -> bool: ...


def link_defect(outgoing: LegShape, incoming: LegShape) -> str | None:
    """The sentence naming why this pair cannot be a self-transfer at all, or
    None when it can. Judged before anything is written."""
    if outgoing.type != "transfer_out" or outgoing.role != "out":
        return "The outgoing side of a match is the out-leg of a transfer out."
    if incoming.type != "transfer_in" or incoming.role != "in":
        return "The incoming side of a match is the in-leg of a transfer in."
    if outgoing.is_numeraire:
        return "The numéraire moves freely — its transfer needs no match."
    if outgoing.instrument_id != incoming.instrument_id:
        return "A self-transfer moves one Instrument — these legs carry two."
    if outgoing.account_id == incoming.account_id:
        return "A self-transfer moves between two Accounts — these legs share one."
    if incoming.quantity > outgoing.quantity:
        return "More arrived than left — that cannot be one self-transfer."
    return None


@dataclass(frozen=True)
class TransferLeg:
    """One side of a transfer, described as the Admin knows it."""

    leg_id: int
    transaction_id: int
    occurred_at: datetime
    note: str | None
    quantity: Decimal
    account_id: int
    account_name: str
    platform_name: str
    instrument_id: int
    instrument_symbol: str
    instrument_name: str


@dataclass(frozen=True)
class Candidate:
    """One proposed pair, awaiting the Admin's decision."""

    outgoing: TransferLeg
    incoming: TransferLeg


@dataclass(frozen=True)
class Decision:
    """One decided pair — a confirmed link or a rejected proposal."""

    id: int
    verdict: str
    decided_at: datetime
    outgoing: TransferLeg
    incoming: TransferLeg


@dataclass(frozen=True)
class MatchingOverview:
    """Everything the matching screen shows: what waits unmatched, what the
    app proposes, and what the Admin has decided."""

    unmatched_outgoing: list[TransferLeg]
    unmatched_incoming: list[TransferLeg]
    candidates: list[Candidate]
    decisions: list[Decision]


def matching_overview(engine: Engine) -> MatchingOverview:
    """The whole matching state, derived — reading it stores nothing."""
    rows = {row.leg_id: row for row in transfer_matches.transfer_legs(engine)}
    legs = {
        row.leg_id: TransferLeg(
            leg_id=row.leg_id,
            transaction_id=row.transaction_id,
            occurred_at=row.occurred_at,
            note=row.note,
            quantity=row.quantity,
            account_id=row.account_id,
            account_name=row.account_name,
            platform_name=row.platform_name,
            instrument_id=row.instrument_id,
            instrument_symbol=row.instrument_symbol,
            instrument_name=row.instrument_name,
        )
        for row in rows.values()
    }
    outgoing = [row for row in rows.values() if row.role == "out"]
    incoming = [row for row in rows.values() if row.role == "in"]
    decisions = [
        decision
        for decision in transfer_matches.list_decisions(engine)
        # A decision survives only while both its legs are transfer legs; a
        # revised Transaction cascades its legs away with the decision.
        if decision.out_leg_id in legs and decision.in_leg_id in legs
    ]
    decided_pairs = {(decision.out_leg_id, decision.in_leg_id) for decision in decisions}
    confirmed_legs = {
        leg_id
        for decision in decisions
        if decision.verdict == "confirmed"
        for leg_id in (decision.out_leg_id, decision.in_leg_id)
    }
    return MatchingOverview(
        unmatched_outgoing=[
            legs[row.leg_id] for row in outgoing if row.leg_id not in confirmed_legs
        ],
        unmatched_incoming=[
            legs[row.leg_id] for row in incoming if row.leg_id not in confirmed_legs
        ],
        candidates=[
            Candidate(outgoing=legs[out.leg_id], incoming=legs[in_.leg_id])
            for out in outgoing
            for in_ in incoming
            if out.leg_id not in confirmed_legs
            and in_.leg_id not in confirmed_legs
            and (out.leg_id, in_.leg_id) not in decided_pairs
            and is_candidate(out, in_)
        ],
        decisions=[
            Decision(
                id=decision.id,
                verdict=decision.verdict,
                decided_at=decision.decided_at,
                outgoing=legs[decision.out_leg_id],
                incoming=legs[decision.in_leg_id],
            )
            for decision in decisions
        ],
    )
