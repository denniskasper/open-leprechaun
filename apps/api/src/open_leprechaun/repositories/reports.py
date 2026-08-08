"""Writes and reads over the Report store (ticket 23). A report row is a
frozen artifact: created once with its figures, its status flipped draft →
final exactly once, and never otherwise updated — regeneration is a new row.

Creation takes the caller's Connection: a report must land in the same
transaction — and snapshot — that stamped its fingerprint, or the stamp could
describe a ledger the figures never saw. Reads take a Connection for the same
reason: a staleness verdict compares the stored fingerprint with the current
inputs, and only one snapshot makes that comparison honest.
"""

import json
from enum import Enum

from sqlalchemy import Connection, Row, text


class Refusal(Enum):
    no_such_report = "no_such_report"
    already_final = "already_final"


def create(connection: Connection, *, year: int, figures: dict) -> int:
    """A new draft report frozen with its figures — never an update."""
    return connection.execute(
        text(
            "INSERT INTO report (year, figures)"
            " VALUES (:year, CAST(:figures AS jsonb)) RETURNING id"
        ),
        {"year": year, "figures": json.dumps(figures)},
    ).scalar_one()


def list_reports(connection: Connection) -> list[Row]:
    """Every report, newest first, without its figures — the lifecycle row a
    listing shows."""
    return list(
        connection.execute(
            text("SELECT id, year, status, generated_at, finalised_at FROM report ORDER BY id DESC")
        ).all()
    )


def get(connection: Connection, report_id: int) -> Row | None:
    return connection.execute(
        text(
            "SELECT id, year, status, generated_at, finalised_at, figures"
            " FROM report WHERE id = :id"
        ),
        {"id": report_id},
    ).one_or_none()


def finalise(connection: Connection, report_id: int) -> Refusal | None:
    """Flip one report draft → final, stamping the instant. The condition is
    in the UPDATE itself, so a report can never be finalised twice."""
    flipped = connection.execute(
        text(
            "UPDATE report SET status = 'final', finalised_at = now()"
            " WHERE id = :id AND status = 'draft'"
        ),
        {"id": report_id},
    )
    if flipped.rowcount == 1:
        return None
    status = connection.execute(
        text("SELECT status FROM report WHERE id = :id"), {"id": report_id}
    ).scalar_one_or_none()
    return Refusal.no_such_report if status is None else Refusal.already_final
