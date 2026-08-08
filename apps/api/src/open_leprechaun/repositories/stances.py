"""Writes and reads over Stances (ADR-0012). The schema holds the scope rule —
dangerous is one global row, kept and ignored one row per Account, absence is
`unacknowledged` — so a decision whose scope disagrees with its stance can
never be stored.

Classifying returns the settled transaction ids, or a Refusal naming which
foundation was missing — the foreign keys are the arbiter, so there is no
check-then-insert race.
"""

from enum import Enum

from sqlalchemy import Engine, Row, text
from sqlalchemy.exc import IntegrityError


class Refusal(Enum):
    """Why a classification did not happen, in the caller's terms."""

    no_such_instrument = "no_such_instrument"
    no_such_account = "no_such_account"
    # A global dangerous verdict outranks any per-Account decision, so a kept
    # or ignored row under one would be dead weight — and a keep would settle
    # inflows under a stance that forbids it. The verdict goes first.
    marked_dangerous = "marked_dangerous"


def classify(
    engine: Engine,
    instrument_id: int,
    *,
    stance: str,
    account_id: int | None = None,
    settle_inflows_as: str | None = None,
) -> list[int] | Refusal:
    """The deliberate act: record the stance and, in the same transaction,
    settle what this pair's pending unclassified inflows were — the type the
    counter-performance answer decided, handed in by the service. A repeated
    decision replaces the earlier one for the same scope; a per-Account
    decision under a standing dangerous verdict is refused, because the
    verdict outranks it — clear the verdict first.

    Returns the settled transaction ids, empty when nothing waited.
    """
    upsert = (
        "INSERT INTO instrument_stance (instrument_id, account_id, stance)"
        " VALUES (:instrument_id, :account_id, :stance)"
        + (
            " ON CONFLICT (instrument_id) WHERE account_id IS NULL DO UPDATE SET decided_at = now()"
            if account_id is None
            else (
                " ON CONFLICT (instrument_id, account_id) WHERE account_id IS NOT NULL"
                " DO UPDATE SET stance = excluded.stance, decided_at = now()"
            )
        )
    )
    try:
        with engine.begin() as connection:
            if account_id is not None:
                condemned = connection.execute(
                    text(
                        "SELECT 1 FROM instrument_stance"
                        " WHERE instrument_id = :instrument_id AND account_id IS NULL"
                    ),
                    {"instrument_id": instrument_id},
                ).scalar_one_or_none()
                if condemned is not None:
                    return Refusal.marked_dangerous
            connection.execute(
                text(upsert),
                {"instrument_id": instrument_id, "account_id": account_id, "stance": stance},
            )
            if settle_inflows_as is None:
                return []
            return [
                row.id
                for row in connection.execute(
                    text(
                        "UPDATE transaction SET type = :settled_type"
                        " WHERE type = 'transfer_in' AND id IN ("
                        "  SELECT transaction_id FROM transaction_leg"
                        "  WHERE instrument_id = :instrument_id AND account_id = :account_id"
                        "  AND role = 'in')"
                        " RETURNING id"
                    ),
                    {
                        "settled_type": settle_inflows_as,
                        "instrument_id": instrument_id,
                        "account_id": account_id,
                    },
                ).all()
            ]
    except IntegrityError as refused:
        return _which_foundation_was_missing(refused)


def clear(engine: Engine, instrument_id: int, account_id: int | None = None) -> bool:
    """Remove a decision, returning the scope to `unacknowledged` — the stance
    describes the present, so removing it means only that the Admin will look
    again. False when there was nothing to remove."""
    with engine.begin() as connection:
        removed = connection.execute(
            text(
                "DELETE FROM instrument_stance WHERE instrument_id = :instrument_id"
                " AND account_id IS NOT DISTINCT FROM :account_id"
            ),
            {"instrument_id": instrument_id, "account_id": account_id},
        )
    return removed.rowcount == 1


def list_stances(engine: Engine, instrument_id: int | None = None) -> list[Row]:
    """Every decision, or one Instrument's — the filter belongs to the query."""
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT id, instrument_id, account_id, stance, decided_at"
                    " FROM instrument_stance"
                    " WHERE CAST(:instrument_id AS integer) IS NULL"
                    " OR instrument_id = :instrument_id"
                    " ORDER BY instrument_id, account_id NULLS FIRST"
                ),
                {"instrument_id": instrument_id},
            ).all()
        )


def list_inbox(engine: Engine) -> list[Row]:
    """Every (Instrument, Account) pair that has arrived — an in-leg exists —
    and that the Admin has never classified, with its pending unclassified
    inflows summarised. The numéraire is exempt: its movement is not a
    disposal and it enters no cost basis, so its arrival waits on nothing."""
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT i.id AS instrument_id, i.family, i.type, i.symbol, i.name,"
                    " i.chain, i.contract_address, i.isin,"
                    " a.id AS account_id, a.name AS account_name, p.name AS platform_name,"
                    " count(*) FILTER (WHERE t.type = 'transfer_in')"
                    "  AS unclassified_inflow_count,"
                    " coalesce(sum(l.quantity) FILTER (WHERE t.type = 'transfer_in'), 0)"
                    "  AS unclassified_quantity,"
                    " max(t.occurred_at) AS last_inflow_at"
                    " FROM transaction_leg l"
                    " JOIN transaction t ON t.id = l.transaction_id"
                    " JOIN instrument i ON i.id = l.instrument_id"
                    " JOIN account a ON a.id = l.account_id"
                    " JOIN platform p ON p.id = a.platform_id"
                    " WHERE l.role = 'in' AND NOT i.is_numeraire"
                    " AND NOT EXISTS (SELECT 1 FROM instrument_stance s"
                    "  WHERE s.instrument_id = i.id"
                    "  AND (s.account_id = a.id OR s.account_id IS NULL))"
                    " GROUP BY i.id, a.id, a.name, p.name"
                    " ORDER BY max(t.occurred_at) DESC, i.symbol, a.id"
                )
            ).all()
        )


def _which_foundation_was_missing(refused: IntegrityError) -> Refusal:
    constraint = getattr(getattr(refused.orig, "diag", None), "constraint_name", None)
    if constraint == "instrument_stance_instrument_fk":
        return Refusal.no_such_instrument
    if constraint == "instrument_stance_account_fk":
        return Refusal.no_such_account
    raise refused
