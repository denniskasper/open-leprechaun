"""Writes and reads over the Staking Delegation marker (ticket 22). A row
says one Instrument is presently delegated at one Account — informational
location, never tax: no engine reads this table and no materialisation
declares it an input. Marking again refreshes the note — the marker describes
the present, so there is nothing to contradict — and removing the row means
"no longer delegated". The foreign keys answer whether the pair exists.
"""

from sqlalchemy import Engine, Row, text
from sqlalchemy.exc import IntegrityError


def mark(engine: Engine, *, instrument_id: int, account_id: int, note: str | None) -> bool:
    """Record that this Instrument is delegated at this Account — False when
    no such Instrument or Account exists."""
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO staking_delegation (instrument_id, account_id, note)"
                    " VALUES (:instrument_id, :account_id, :note)"
                    " ON CONFLICT (instrument_id, account_id)"
                    " DO UPDATE SET note = EXCLUDED.note, marked_at = now()"
                ),
                {"instrument_id": instrument_id, "account_id": account_id, "note": note},
            )
    except IntegrityError as refused:
        # Only the pair's existence is the caller's to get wrong; anything
        # else refusing here is a genuine fault.
        constraint = getattr(getattr(refused.orig, "diag", None), "constraint_name", None)
        if constraint in ("staking_delegation_instrument_fk", "staking_delegation_account_fk"):
            return False
        raise
    return True


def unmark(engine: Engine, *, instrument_id: int, account_id: int) -> bool:
    """No longer delegated — False when no marker was standing."""
    with engine.begin() as connection:
        removed = connection.execute(
            text(
                "DELETE FROM staking_delegation"
                " WHERE instrument_id = :instrument_id AND account_id = :account_id"
            ),
            {"instrument_id": instrument_id, "account_id": account_id},
        )
    return removed.rowcount == 1


def list_markers(engine: Engine) -> list[Row]:
    """Every standing marker, with the names the Admin knows the pair by."""
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT d.instrument_id, i.symbol, i.name AS instrument_name,"
                    " d.account_id, a.name AS account_name, p.name AS platform_name,"
                    " d.note, d.marked_at"
                    " FROM staking_delegation d"
                    " JOIN instrument i ON i.id = d.instrument_id"
                    " JOIN account a ON a.id = d.account_id"
                    " JOIN platform p ON p.id = a.platform_id"
                    " ORDER BY p.name, a.name, i.symbol"
                )
            ).all()
        )
