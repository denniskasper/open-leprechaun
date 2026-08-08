"""What the application knows about the ledger beyond storage: the transaction
vocabulary with the legs each type must and must not carry — balance is
structural, so a buy cannot be recorded without the cash it spent — and the
overview that hands the UI every Transaction with its legs nested under it.

Each type's tax consequence is deliberately not here: it is documented once in
services/tax_treatment.py, which the tax engines alone will read.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Engine

from open_leprechaun.repositories import transactions
from open_leprechaun.repositories.transactions import Leg


@dataclass(frozen=True)
class LegRules:
    """Which roles an event of this type must record, and which it must not."""

    requires: frozenset[str]
    forbids: frozenset[str] = frozenset()


_INFLOW_ONLY = LegRules(requires=frozenset({"in"}), forbids=frozenset({"out"}))

TRANSACTION_TYPES: Mapping[str, LegRules] = {
    # One Instrument exchanged for another: a buy, a sell, a crypto-crypto
    # trade or a currency conversion — the other side is required, so the
    # disposal of what was spent is never silently missing.
    "trade": LegRules(requires=frozenset({"in", "out"})),
    # Assets arrived or left. Each side is its own Transaction recorded where
    # it happened; self-transfer matching (ticket 16) links the two.
    "transfer_in": _INFLOW_ONLY,
    "transfer_out": LegRules(requires=frozenset({"out"}), forbids=frozenset({"in"})),
    # Assets given for goods or services outside the ledger.
    "spend": LegRules(requires=frozenset({"out"}), forbids=frozenset({"in"})),
    # Crypto income, named for what actually happened.
    "staking_reward": _INFLOW_ONLY,
    "lending_interest": _INFLOW_ONLY,
    "mining_reward": _INFLOW_ONLY,
    "airdrop": _INFLOW_ONLY,
    # Securities and cash income.
    "dividend": _INFLOW_ONLY,
    "distribution": _INFLOW_ONLY,
    "interest": _INFLOW_ONLY,
    # A standalone cost — custody or account maintenance — with no enabling
    # leg to attach to.
    "fee": LegRules(requires=frozenset({"fee"}), forbids=frozenset({"in", "out"})),
}

_ROLE_PHRASES = {"in": "what arrived", "out": "what left", "fee": "what the fee consumed"}


def structural_defect(type: str, legs: Sequence[Leg]) -> str | None:
    """The sentence naming why this set of legs does not balance for this
    type, or None when it does. Judged before anything is written, so an
    unbalanced event can never exist to be repaired later."""
    label = type.replace("_", " ")
    rules = TRANSACTION_TYPES[type]
    roles = {leg.role for leg in legs}
    for role in sorted(rules.requires - roles):
        return f"A {label} records {_ROLE_PHRASES[role]}, and this one is missing it."
    for role in sorted(rules.forbids & roles):
        return f"A {label} does not record {_ROLE_PHRASES[role]} — that is its own Transaction."
    return _attachment_defect(legs)


def _attachment_defect(legs: Sequence[Leg]) -> str | None:
    for position, leg in enumerate(legs):
        if leg.charged_against is None:
            continue
        if leg.role != "fee":
            return "Only a fee attaches to another leg."
        target_in_reach = 0 <= leg.charged_against < len(legs)
        if not target_in_reach or leg.charged_against == position:
            return "A fee attaches to another leg of the same Transaction."
        if legs[leg.charged_against].role == "fee":
            return "A fee attaches to the leg it was charged against, never to another fee."
    return None


@dataclass(frozen=True)
class LegOverview:
    id: int
    account_id: int
    instrument_id: int
    role: str
    quantity: Decimal
    charged_against_leg_id: int | None


@dataclass(frozen=True)
class TransactionOverview:
    id: int
    type: str
    occurred_at: datetime
    note: str | None
    legs: tuple[LegOverview, ...]


def overview(engine: Engine) -> list[TransactionOverview]:
    legs_of: dict[int, list[LegOverview]] = {}
    for row in transactions.list_legs(engine):
        legs_of.setdefault(row.transaction_id, []).append(
            LegOverview(
                id=row.id,
                account_id=row.account_id,
                instrument_id=row.instrument_id,
                role=row.role,
                quantity=row.quantity,
                charged_against_leg_id=row.charged_against_leg_id,
            )
        )
    return [
        TransactionOverview(
            id=row.id,
            type=row.type,
            occurred_at=row.occurred_at,
            note=row.note,
            legs=tuple(legs_of.get(row.id, [])),
        )
        for row in transactions.list_transactions(engine)
    ]


__all__ = ["TRANSACTION_TYPES", "Leg", "LegRules", "overview", "structural_defect"]
