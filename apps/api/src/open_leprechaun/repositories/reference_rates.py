"""Writes and reads over the stored reference rates (ticket 17). A row per
currency and date holds either the published rate or, as NULL, a checked
absence — a past date the ECB published nothing for. Stored rows are
immutable — the inserts never overwrite — so a figure a past conversion
produced can always be reproduced from the store, whatever a source would
answer today.
"""

from collections.abc import Iterable
from datetime import date

from sqlalchemy import Engine, Row, text

from open_leprechaun.ports.reference_rates import ReferenceRate


def store(engine: Engine, rates: Iterable[ReferenceRate]) -> None:
    """Keep every published rate not already held. ON CONFLICT DO NOTHING is
    the immutability: the first stored row for a currency and date wins
    forever."""
    rows = [
        {"currency": rate.currency, "rate_date": rate.rate_date, "rate": rate.rate}
        for rate in rates
    ]
    if not rows:
        return
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO reference_rate (currency, rate_date, rate)"
                " VALUES (:currency, :rate_date, :rate)"
                " ON CONFLICT DO NOTHING"
            ),
            rows,
        )


def record_absences(engine: Engine, *, currency: str, dates: Iterable[date]) -> None:
    """Keep a checked absence — NULL rate — for each date the source was
    asked about and published nothing for, so the fallback answers from the
    store instead of asking again. A publication already held wins."""
    rows = [{"currency": currency, "rate_date": rate_date} for rate_date in dates]
    if not rows:
        return
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO reference_rate (currency, rate_date, rate)"
                " VALUES (:currency, :rate_date, NULL)"
                " ON CONFLICT DO NOTHING"
            ),
            rows,
        )


def covered(engine: Engine, *, currency: str, on: date) -> bool:
    """Whether the store already holds an answer for this date — a published
    rate or a checked absence — so no fetch is needed."""
    with engine.connect() as connection:
        return (
            connection.execute(
                text("SELECT 1 FROM reference_rate WHERE currency = :currency AND rate_date = :on"),
                {"currency": currency, "on": on},
            ).first()
            is not None
        )


def latest_on_or_before(engine: Engine, *, currency: str, on: date, floor: date) -> Row | None:
    """The most recent published rate on or before `on`, ignoring checked
    absences and anything older than `floor` — the bound that keeps a data
    gap from silently resolving to a months-old rate."""
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT currency, rate_date, rate FROM reference_rate"
                " WHERE currency = :currency AND rate_date BETWEEN :floor AND :on"
                " AND rate IS NOT NULL"
                " ORDER BY rate_date DESC LIMIT 1"
            ),
            {"currency": currency, "on": on, "floor": floor},
        ).first()
