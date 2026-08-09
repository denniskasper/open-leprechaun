"""Reads the pre-flight checks (ticket 25) ask of the ledger. Activity is
bucketed into years by the Europe/Berlin local date of each event's instant —
the same clock that bounds the Tax Year (services/fx.event_date), expressed
in SQL so a check never hauls the ledger into Python to ask which year a leg
belongs to.
"""

from sqlalchemy import Engine, Row, text


def unacknowledged_arrivals(engine: Engine, *, year: int) -> list[Row]:
    """Every (Instrument, Account) pair with an arrival up to the end of the
    Tax Year that the Admin has never classified — the inbox's own criteria
    (repositories/stances.list_inbox), bounded by the year: the numéraire is
    exempt, and a confirmed self-transfer's in-leg waits on nothing."""
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT DISTINCT l.instrument_id, l.account_id, i.symbol"
                    " FROM transaction_leg l"
                    " JOIN transaction t ON t.id = l.transaction_id"
                    " JOIN instrument i ON i.id = l.instrument_id"
                    " WHERE l.role = 'in' AND NOT i.is_numeraire"
                    " AND extract(year FROM t.occurred_at AT TIME ZONE 'Europe/Berlin')"
                    "  <= :year"
                    " AND NOT EXISTS (SELECT 1 FROM instrument_stance s"
                    "  WHERE s.instrument_id = l.instrument_id"
                    "  AND (s.account_id = l.account_id OR s.account_id IS NULL))"
                    " AND NOT EXISTS (SELECT 1 FROM transfer_match m"
                    "  WHERE m.in_leg_id = l.id AND m.verdict = 'confirmed')"
                    " ORDER BY i.symbol, l.instrument_id, l.account_id"
                ),
                {"year": year},
            ).all()
        )


def active_instrument_ids(engine: Engine, *, year: int) -> set[int]:
    """Every Instrument with a leg on a transaction of this Tax Year."""
    with engine.connect() as connection:
        return {
            row.instrument_id
            for row in connection.execute(
                text(
                    "SELECT DISTINCT l.instrument_id"
                    " FROM transaction_leg l JOIN transaction t ON t.id = l.transaction_id"
                    " WHERE extract(year FROM t.occurred_at AT TIME ZONE 'Europe/Berlin')"
                    "  = :year"
                ),
                {"year": year},
            )
        }
