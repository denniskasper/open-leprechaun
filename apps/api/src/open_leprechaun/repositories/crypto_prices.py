"""Writes and reads over the stored crypto prices (ticket 18).

`crypto_price` is the last known price per Instrument — one row a fresh quote
overwrites, because it answers "what was it worth when someone last knew",
not "what has it ever been worth". `crypto_daily_close` is history: one close
per Instrument and day, first stored wins, so a backfill re-run can never
silently shift a figure a chart already showed.
"""

from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Engine, Row, text


def priceable_instruments(engine: Engine) -> list[Row]:
    """Every crypto Instrument the provider chain prices. Excluded, each for
    its own documented reason: a stablecoin, whose EUR value comes from its
    peg's daily reference rate (ADR-0017); a dangerous Instrument, and one
    ignored without being kept anywhere — neither may ever acquire a price
    source (ADR-0012)."""
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT id, type, symbol, name, chain, contract_address FROM instrument i"
                    " WHERE family = 'crypto' AND pegged_currency IS NULL"
                    " AND NOT EXISTS (SELECT 1 FROM instrument_stance s"
                    "  WHERE s.instrument_id = i.id AND s.account_id IS NULL)"
                    " AND (NOT EXISTS (SELECT 1 FROM instrument_stance s"
                    "   WHERE s.instrument_id = i.id AND s.stance = 'ignored')"
                    "  OR EXISTS (SELECT 1 FROM instrument_stance s"
                    "   WHERE s.instrument_id = i.id AND s.stance = 'kept'))"
                    " ORDER BY symbol, id"
                )
            ).all()
        )


def store_quote(
    engine: Engine, *, instrument_id: int, price_eur: Decimal, source: str, as_of: datetime
) -> None:
    """Keep a fresh quote as the last known price, replacing whatever was
    known before — this row answers for the present, so newer wins."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO crypto_price (instrument_id, price_eur, source, as_of)"
                " VALUES (:instrument_id, :price_eur, :source, :as_of)"
                " ON CONFLICT (instrument_id) DO UPDATE"
                " SET price_eur = excluded.price_eur, source = excluded.source,"
                " as_of = excluded.as_of"
            ),
            {
                "instrument_id": instrument_id,
                "price_eur": price_eur,
                "source": source,
                "as_of": as_of,
            },
        )


def last_known(engine: Engine, instrument_id: int) -> Row | None:
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT instrument_id, price_eur, source, as_of FROM crypto_price"
                " WHERE instrument_id = :instrument_id"
            ),
            {"instrument_id": instrument_id},
        ).one_or_none()


def store_daily_closes(
    engine: Engine,
    instrument_id: int,
    *,
    source: str,
    closes: Iterable[tuple[date, Decimal]],
) -> int:
    """Keep every close not already held — the first stored close for a day
    wins forever — answering how many this call actually added."""
    rows = [
        {
            "instrument_id": instrument_id,
            "close_date": close_date,
            "price_eur": price_eur,
            "source": source,
        }
        for close_date, price_eur in closes
    ]
    if not rows:
        return 0
    with engine.begin() as connection:
        return connection.execute(
            text(
                "INSERT INTO crypto_daily_close (instrument_id, close_date, price_eur, source)"
                " VALUES (:instrument_id, :close_date, :price_eur, :source)"
                " ON CONFLICT DO NOTHING"
            ),
            rows,
        ).rowcount


def daily_closes(engine: Engine, instrument_id: int, *, start: date, end: date) -> list[Row]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT close_date, price_eur, source FROM crypto_daily_close"
                    " WHERE instrument_id = :instrument_id"
                    " AND close_date BETWEEN :start AND :end"
                    " ORDER BY close_date"
                ),
                {"instrument_id": instrument_id, "start": start, "end": end},
            ).all()
        )
