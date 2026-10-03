"""Corporate Actions (ticket 52): issuer events that change a holding
without a trade — split and reverse split, spin-off, merger, capital return
— recorded as events and never as edits to lots.

The lot engine walks the events beside the ledger (services/lots), so this
module decides only what may be recorded and shows what an event does. A
**preview** derives the ledger with the proposed event walked beside the
stored ones and answers the before and after of every lot open at its
instant, writing nothing; applying it is recording the event; **reversing**
it is removing the event — the next derivation simply no longer meets it
(ADR-0014), and the `corporate_actions` input class marks every stored
materialisation and report stale by itself.

Where the treatment is fact-specific the application records and refuses to
assert: a spin-off moves the share of basis the Admin supplied and a merger
carries the basis across at the exchange ratio the Admin supplied, and both
stand **flagged for manual review** until the Admin marks them reviewed — as
does a capital return that exceeded a lot's basis — or met one still awaiting
its valuation, which nobody can yet say it did not exceed — because what an
excess is taxed as is no arithmetic of this module's. The flag is prose about the
event: reviewing changes no figure.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Engine, Row

from open_leprechaun.repositories import corporate_actions as repository
from open_leprechaun.repositories import instruments
from open_leprechaun.repositories.corporate_actions import CorporateAction
from open_leprechaun.services import fx, lots
from open_leprechaun.services.lots import LotEffect

__all__ = [
    "FACT_SPECIFIC_KINDS",
    "CorporateAction",
    "Recorded",
    "RefusedError",
    "awaiting_review",
    "mark_reviewed",
    "preview",
    "record",
    "recorded",
    "remove",
]

FACT_SPECIFIC_KINDS = ("spin_off", "merger")
"""The kinds whose tax treatment turns on facts the ledger does not hold —
recorded by the ratio the Admin supplies, and flagged for manual review."""

_HOLDABLE_FAMILIES = ("security", "crypto")
"""What an issuer event can act on: a security, or a crypto asset its issuer
redenominates or swaps. Cash has no issuer event — a currency that changes is
a different Instrument, exchanged by a trade."""


class RefusedError(Exception):
    """The event cannot be recorded as stated; the message says why."""


@dataclass(frozen=True)
class Recorded:
    """One event with what it did: every lot open at its instant, before and
    after. `needs_review` stands until the Admin marks a fact-specific event
    reviewed."""

    id: int | None
    kind: str
    instrument_id: int
    effective_at: datetime
    units_new: Decimal | None
    units_old: Decimal | None
    target_instrument_id: int | None
    basis_share: Decimal | None
    amount_per_unit_eur: Decimal | None
    note: str | None
    reviewed_at: datetime | None
    needs_review: bool
    effects: tuple[LotEffect, ...]


def preview(engine: Engine, action: CorporateAction) -> Recorded:
    """What the event would do, written nowhere: the ledger derived with the
    proposal walked beside the stored events, on one snapshot. Raises RefusedError
    for an event that could not be recorded either."""
    _judge(engine, action)
    with lots.snapshot(engine) as connection:
        derived = lots.derive_on(connection, proposed=[action])
    return _with_effects(action, derived.effects.get(None, []))


def record(engine: Engine, action: CorporateAction) -> int:
    """Apply the event by recording it — nothing else is written, because
    every lot is derived. Raises RefusedError where the event is not one."""
    _judge(engine, action)
    return repository.create(engine, action)


def recorded(engine: Engine) -> list[Recorded]:
    """Every recorded event, newest effect first, each with what it did to
    the lots open at its instant — all from one derivation, so the list can
    never show an effect the figures do not rest on."""
    with lots.snapshot(engine) as connection:
        derived = lots.derive_on(connection)
        rows = repository.action_rows(connection)
    return [_with_effects(row, derived.effects.get(row.id, [])) for row in reversed(rows)]


def remove(engine: Engine, action_id: int) -> bool:
    """Reverse the event: remove it, and the next derivation rebuilds every
    lot without it. False when there was none to remove."""
    return repository.delete(engine, action_id)


def mark_reviewed(engine: Engine, action_id: int) -> bool:
    """The Admin has looked at a flagged event and stands by what it states.
    False when no such event exists."""
    return repository.mark_reviewed(engine, action_id)


def awaiting_review(engine: Engine, *, through_year: int) -> list[Recorded]:
    """The flagged events in effect up to the end of the Tax Year — each one
    a figure of that year may rest on."""
    return [
        action
        for action in recorded(engine)
        if action.needs_review and fx.event_date(action.effective_at).year <= through_year
    ]


def _with_effects(action: CorporateAction | Row, effects: list[LotEffect]) -> Recorded:
    # A return that exceeded a lot's basis — or one taken off a basis only
    # a report can state, where nobody can yet say whether it did.
    exceeded = any(effect.excess_eur > 0 for effect in effects) or (
        action.kind == "capital_return"
        and any(effect.before.basis_eur is None for effect in effects)
    )
    return Recorded(
        id=action.id,
        kind=action.kind,
        instrument_id=action.instrument_id,
        effective_at=action.effective_at,
        units_new=action.units_new,
        units_old=action.units_old,
        target_instrument_id=action.target_instrument_id,
        basis_share=action.basis_share,
        amount_per_unit_eur=action.amount_per_unit_eur,
        note=action.note,
        reviewed_at=action.reviewed_at,
        needs_review=action.reviewed_at is None
        and (action.kind in FACT_SPECIFIC_KINDS or exceeded),
        effects=tuple(effects),
    )


def _judge(engine: Engine, action: CorporateAction) -> None:
    """Whether the event names things an issuer event can act on. The shape
    each kind carries is the router's and the schema's; this is what neither
    can see."""
    _holdable(engine, action.instrument_id, "the Instrument")
    if action.target_instrument_id is not None:
        if action.target_instrument_id == action.instrument_id:
            raise RefusedError(
                "The target is the Instrument itself — a change of units within one"
                " Instrument is a split."
            )
        _holdable(engine, action.target_instrument_id, "the target Instrument")


def _holdable(engine: Engine, instrument_id: int, role: str) -> None:
    instrument = instruments.get(engine, instrument_id)
    if instrument is None:
        raise RefusedError(f"No such Instrument: {role} is unknown.")
    if instrument.family not in _HOLDABLE_FAMILIES:
        raise RefusedError(
            f"{instrument.symbol} is {instrument.family} — a Corporate Action acts on a"
            " security or a crypto asset."
        )
