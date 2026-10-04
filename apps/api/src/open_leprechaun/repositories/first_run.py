"""What the first-run checklist (ticket 58) asks of the database: whether
each thing the walk produces exists yet. Read-only — the checklist derives
its state and stores none."""

from sqlalchemy import Engine, Row, text

__all__ = ["activity_years", "admin_exists", "reconciliations", "tally"]


def admin_exists(engine: Engine) -> bool:
    with engine.connect() as connection:
        return connection.execute(text("SELECT EXISTS (SELECT 1 FROM admin_user)")).scalar_one()


def tally(engine: Engine) -> Row:
    """How many of each thing the walk produces the database holds."""
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT"
                " (SELECT count(*) FROM platform) AS platforms,"
                " (SELECT count(*) FROM account) AS accounts,"
                " (SELECT count(*) FROM connection) AS connections,"
                " (SELECT count(*) FROM import_batch) AS import_batches,"
                " (SELECT count(*) FROM transaction) AS transactions,"
                " (SELECT count(*) FROM report) AS reports"
            )
        ).one()


def reconciliations(engine: Engine) -> list[Row]:
    """Every Connection beside what reconciling it last came to — the
    reconciliation columns NULL where it has never been reconciled."""
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT c.id, c.label, c.venue, r.reconciled_at, r.gaps, r.failed_kinds"
                    " FROM connection c"
                    " LEFT JOIN connection_reconciliation r ON r.connection_id = c.id"
                    " ORDER BY c.platform_id, c.label, c.id"
                )
            ).all()
        )


def activity_years(engine: Engine) -> list[int]:
    """Every Tax Year in which anything happened — a Transaction executed or
    a futures position closed — oldest first, by the Europe/Berlin clock that
    buckets Tax Years."""
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT DISTINCT"
                    " extract(year FROM at AT TIME ZONE 'Europe/Berlin')::int AS year FROM ("
                    " SELECT occurred_at AS at FROM transaction"
                    " UNION ALL"
                    " SELECT closed_at FROM futures_position WHERE closed_at IS NOT NULL"
                    ") AS activity ORDER BY year"
                )
            ).scalars()
        )
