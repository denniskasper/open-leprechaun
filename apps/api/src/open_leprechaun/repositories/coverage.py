"""Reads for the coverage warnings (ticket 40): which paired Accounts carry a
claimed sync window, and when each Account's recorded activity begins.

Coverage is judged per Account, because the Account is where records land —
the claimed window comes from connection_adapter_status, the recorded
activity from the ledger and the futures tables together.
"""

from datetime import datetime

from sqlalchemy import Engine, Row, text


def covered_pairings(engine: Engine) -> list[Row]:
    """Every (Connection, kind) whose sync has claimed a bounded window, with
    the Account it writes into and the names the warning speaks in. A kind
    that never synced, or whose venue reaches all history, claims nothing and
    appears nowhere."""
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT status.connection_id, status.adapter_kind, status.covered_from,"
                    " c.label AS connection_label, c.venue,"
                    " p.name AS platform_name,"
                    " pairing.account_id, a.name AS account_name"
                    " FROM connection_adapter_status status"
                    " JOIN connection c ON c.id = status.connection_id"
                    " JOIN platform p ON p.id = c.platform_id"
                    " JOIN connection_account pairing"
                    "  ON pairing.connection_id = status.connection_id"
                    "  AND pairing.adapter_kind = status.adapter_kind"
                    " JOIN account a ON a.id = pairing.account_id"
                    " WHERE status.covered_from IS NOT NULL"
                    " ORDER BY status.connection_id, status.adapter_kind"
                )
            ).all()
        )


def earliest_activity_by_account(engine: Engine) -> dict[int, datetime]:
    """When each Account's recorded history begins: the earliest instant over
    ledger Transactions, futures Fills and Funding Fees — whatever the
    source, because imported and hand-recorded activity count alike."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT account_id, MIN(occurred_at) AS earliest FROM ("
                " SELECT leg.account_id, t.occurred_at"
                "  FROM transaction_leg leg"
                "  JOIN transaction t ON t.id = leg.transaction_id"
                " UNION ALL SELECT account_id, occurred_at FROM futures_fill"
                " UNION ALL SELECT account_id, occurred_at FROM funding_payment"
                ") activity GROUP BY account_id"
            )
        ).all()
    return {row.account_id: row.earliest for row in rows}
