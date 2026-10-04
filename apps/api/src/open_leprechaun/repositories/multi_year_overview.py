"""What the multi-year overview (ticket 57) asks of the database that no
engine already answers: how far the ledger reaches in time."""

from datetime import datetime

from sqlalchemy import Engine, text

__all__ = ["activity_span"]


def activity_span(engine: Engine) -> tuple[datetime, datetime] | None:
    """The first and last instant anything with a Tax Year happened — a
    Transaction executed or a futures position closed — or None for a ledger
    holding neither."""
    with engine.connect() as connection:
        first, last = connection.execute(
            text(
                "SELECT min(at), max(at) FROM ("
                " SELECT occurred_at AS at FROM transaction"
                " UNION ALL"
                " SELECT closed_at FROM futures_position WHERE closed_at IS NOT NULL"
                ") AS activity"
            )
        ).one()
    return None if first is None else (first, last)
