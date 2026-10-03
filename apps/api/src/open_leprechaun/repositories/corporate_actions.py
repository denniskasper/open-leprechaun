"""Writes and reads over Corporate Actions (ticket 52): the events
themselves, never their effect. What an event did to a holding is derived by
the lot engine every time it is asked (ADR-0014), so recording one is a
single insert and reversing one is a single delete — there is no lot state
here to restore.
"""

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Connection, Engine, Row, text

_COLUMNS = (
    "id, kind, instrument_id, effective_at, units_new, units_old, target_instrument_id,"
    " basis_share, amount_per_unit_eur, note, reviewed_at"
)


@dataclass(frozen=True)
class CorporateAction:
    """One event as handed in — proposed for a preview or recorded for good.
    It reads like a stored row with no id yet, so the derivation walks either
    alike. Which fields a kind carries is the schema's to hold."""

    kind: str
    instrument_id: int
    effective_at: datetime
    units_new: Decimal | None = None
    units_old: Decimal | None = None
    target_instrument_id: int | None = None
    basis_share: Decimal | None = None
    amount_per_unit_eur: Decimal | None = None
    note: str | None = None
    id: int | None = None
    reviewed_at: datetime | None = None


def action_rows(connection: Connection) -> list[Row]:
    """Every event in effect order — a derivation input, read on the
    caller's snapshot like every other."""
    return list(
        connection.execute(
            text(f"SELECT {_COLUMNS} FROM corporate_action ORDER BY effective_at, id")
        ).all()
    )


def create(engine: Engine, action: CorporateAction) -> int:
    """Record the event. Whether it may be recorded — its Instruments, its
    kind's own fields — is the service's judgement, made before this is
    called; the schema holds the same shape regardless."""
    with engine.begin() as connection:
        return connection.execute(
            text(
                "INSERT INTO corporate_action (kind, instrument_id, effective_at, units_new,"
                " units_old, target_instrument_id, basis_share, amount_per_unit_eur, note)"
                " VALUES (:kind, :instrument_id, :effective_at, :units_new, :units_old,"
                " :target_instrument_id, :basis_share, :amount_per_unit_eur, :note)"
                " RETURNING id"
            ),
            asdict(action),
        ).scalar_one()


def delete(engine: Engine, action_id: int) -> bool:
    """Remove the event. False when there was none to remove."""
    with engine.begin() as connection:
        removed = connection.execute(
            text("DELETE FROM corporate_action WHERE id = :action_id"), {"action_id": action_id}
        )
    return removed.rowcount == 1


def mark_reviewed(engine: Engine, action_id: int) -> bool:
    """Stamp the Admin's review on the event; the first stamp stands. False
    when no such event exists."""
    with engine.begin() as connection:
        marked = connection.execute(
            text(
                "UPDATE corporate_action SET reviewed_at = COALESCE(reviewed_at, now())"
                " WHERE id = :action_id"
            ),
            {"action_id": action_id},
        )
    return marked.rowcount == 1
