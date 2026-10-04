"""Writes and reads over the stored portfolio snapshots (ticket 54): one row
per Europe/Berlin calendar date, the day's latest measurement.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Engine, Row, text

_COLUMNS = (
    "snapshot_date, taken_at, value_eur, positions_held, positions_counted,"
    " contributions_eur, withdrawals_eur, unvalued_flows"
)


def store(
    engine: Engine,
    *,
    snapshot_date: date,
    taken_at: datetime,
    value_eur: Decimal | None,
    positions_held: int,
    positions_counted: int,
    contributions_eur: Decimal,
    withdrawals_eur: Decimal,
    unvalued_flows: int,
) -> None:
    """Keep the day's measurement, replacing an earlier one of the same day —
    a day has one point, its latest."""
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO portfolio_snapshot ({_COLUMNS})"
                " VALUES (:snapshot_date, :taken_at, :value_eur, :positions_held,"
                " :positions_counted, :contributions_eur, :withdrawals_eur, :unvalued_flows)"
                " ON CONFLICT (snapshot_date) DO UPDATE SET"
                " taken_at = EXCLUDED.taken_at, value_eur = EXCLUDED.value_eur,"
                " positions_held = EXCLUDED.positions_held,"
                " positions_counted = EXCLUDED.positions_counted,"
                " contributions_eur = EXCLUDED.contributions_eur,"
                " withdrawals_eur = EXCLUDED.withdrawals_eur,"
                " unvalued_flows = EXCLUDED.unvalued_flows"
            ),
            {
                "snapshot_date": snapshot_date,
                "taken_at": taken_at,
                "value_eur": value_eur,
                "positions_held": positions_held,
                "positions_counted": positions_counted,
                "contributions_eur": contributions_eur,
                "withdrawals_eur": withdrawals_eur,
                "unvalued_flows": unvalued_flows,
            },
        )


def list_snapshots(engine: Engine) -> list[Row]:
    """Every stored snapshot, oldest first."""
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(f"SELECT {_COLUMNS} FROM portfolio_snapshot ORDER BY snapshot_date")
            ).all()
        )
