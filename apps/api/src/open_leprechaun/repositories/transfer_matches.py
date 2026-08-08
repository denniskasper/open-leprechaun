"""Writes and reads over self-transfer match decisions (ticket 16). A row is
one deliberate act of the Admin over one (out-leg, in-leg) pair — confirmed or
rejected; a candidate is a derived query and never a row, so absence means
nobody has decided yet. The schema is the arbiter: the foreign keys answer
whether the legs exist, the partial unique indexes hold each leg to one
confirmed match, and the pair key keeps confirm and reject from contradicting
each other — no check-then-insert races.
"""

from enum import Enum

from sqlalchemy import Engine, Row, text
from sqlalchemy.exc import IntegrityError


class Refusal(Enum):
    """Why a decision did not happen, in the caller's terms."""

    no_such_leg = "no_such_leg"
    # One of the legs already belongs to a confirmed match — a parcel cannot
    # arrive twice, or leave for two destinations.
    already_matched = "already_matched"
    # This pair already carries a decision; undo it before deciding again.
    already_decided = "already_decided"


def decide(engine: Engine, *, out_leg_id: int, in_leg_id: int, verdict: str) -> int | Refusal:
    """Record the Admin's decision over one proposed pair."""
    try:
        with engine.begin() as connection:
            return connection.execute(
                text(
                    "INSERT INTO transfer_match (out_leg_id, in_leg_id, verdict)"
                    " VALUES (:out_leg_id, :in_leg_id, :verdict) RETURNING id"
                ),
                {"out_leg_id": out_leg_id, "in_leg_id": in_leg_id, "verdict": verdict},
            ).scalar_one()
    except IntegrityError as refused:
        return _which_rule_refused(refused)


def undo(engine: Engine, match_id: int) -> bool:
    """Remove a decision, returning the pair to undecided — a confirmed link
    unlinks, a rejected pair becomes proposable again. False when there was
    nothing to remove."""
    with engine.begin() as connection:
        removed = connection.execute(
            text("DELETE FROM transfer_match WHERE id = :id"), {"id": match_id}
        )
    return removed.rowcount == 1


def list_decisions(engine: Engine) -> list[Row]:
    """Every decision, newest first."""
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT id, out_leg_id, in_leg_id, verdict, decided_at"
                    " FROM transfer_match ORDER BY decided_at DESC, id DESC"
                )
            ).all()
        )


def transfer_legs(engine: Engine) -> list[Row]:
    """Every transfer leg the matching screen reasons about: the out-leg of
    each transfer_out and the in-leg of each transfer_in, with the names the
    Admin knows them by. The numéraire is exempt — moving it is no disposal,
    so it never awaits a match."""
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT l.id AS leg_id, l.transaction_id, t.type, t.occurred_at, t.note,"
                    " l.role, l.quantity, l.account_id, a.name AS account_name,"
                    " p.name AS platform_name, l.instrument_id, i.symbol AS instrument_symbol,"
                    " i.name AS instrument_name"
                    " FROM transaction_leg l"
                    " JOIN transaction t ON t.id = l.transaction_id"
                    " JOIN instrument i ON i.id = l.instrument_id"
                    " JOIN account a ON a.id = l.account_id"
                    " JOIN platform p ON p.id = a.platform_id"
                    " WHERE NOT i.is_numeraire"
                    " AND ((t.type = 'transfer_out' AND l.role = 'out')"
                    "  OR (t.type = 'transfer_in' AND l.role = 'in'))"
                    " ORDER BY t.occurred_at, l.id"
                )
            ).all()
        )


def leg_details(engine: Engine, leg_ids: list[int]) -> dict[int, Row]:
    """What judging a proposed pair needs to know about each leg."""
    with engine.connect() as connection:
        return {
            row.id: row
            for row in connection.execute(
                text(
                    "SELECT l.id, l.role, l.quantity, l.account_id, l.instrument_id,"
                    " t.type, i.is_numeraire"
                    " FROM transaction_leg l"
                    " JOIN transaction t ON t.id = l.transaction_id"
                    " JOIN instrument i ON i.id = l.instrument_id"
                    " WHERE l.id = ANY(:leg_ids)"
                ),
                {"leg_ids": leg_ids},
            ).all()
        }


def _which_rule_refused(refused: IntegrityError) -> Refusal:
    constraint = getattr(getattr(refused.orig, "diag", None), "constraint_name", None)
    if constraint in ("transfer_match_out_leg_fk", "transfer_match_in_leg_fk"):
        return Refusal.no_such_leg
    if constraint in (
        "transfer_match_out_leg_once_confirmed",
        "transfer_match_in_leg_once_confirmed",
    ):
        return Refusal.already_matched
    if constraint == "transfer_match_one_decision_per_pair":
        return Refusal.already_decided
    raise refused
