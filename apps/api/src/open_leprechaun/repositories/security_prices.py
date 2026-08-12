"""Writes and reads over the stored security prices (ticket 45).

`security_price` is the last known price per Instrument — one row a fresh
quote overwrites, carrying the currency and venue the quote was made in
alongside the source, because it answers "what was it worth when someone
last knew", not "what has it ever been worth". `security_daily_close` is
history: one close per Instrument and day, first stored wins, so a backfill
re-run can never silently shift a figure a chart already showed.
"""

from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Engine, Row, text

from open_leprechaun.repositories.stances import UNBARRED_FROM_PRICING_SQL


def priceable_securities(engine: Engine) -> list[Row]:
    """Every security the provider prices or the store answers for — barred
    stances excluded (ADR-0012). A security without a price-source Listing
    still belongs here: it is served as stale or unpriced by name, never
    silently dropped from the report."""
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT id, symbol, name FROM instrument i"
                    f" WHERE family = 'security'{UNBARRED_FROM_PRICING_SQL}"
                    " ORDER BY symbol, id"
                )
            ).all()
        )


def price_source_listings(engine: Engine) -> list[Row]:
    """The Listing each priceable security's price source names — what the
    provider is asked for, one market per Instrument."""
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT l.instrument_id, i.isin, l.venue, l.quote_currency"
                    " FROM listing l JOIN instrument i ON i.id = l.instrument_id"
                    f" WHERE l.price_source AND i.family = 'security'{UNBARRED_FROM_PRICING_SQL}"
                    " ORDER BY i.symbol, l.instrument_id"
                )
            ).all()
        )


def store_quote(
    engine: Engine,
    *,
    instrument_id: int,
    price_eur: Decimal,
    quote_currency: str,
    venue: str,
    source: str,
    as_of: datetime,
) -> None:
    """Keep a fresh quote as the last known price, replacing whatever was
    known before — this row answers for the present, so newer wins."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO security_price"
                " (instrument_id, price_eur, quote_currency, venue, source, as_of)"
                " VALUES (:instrument_id, :price_eur, :quote_currency, :venue, :source, :as_of)"
                " ON CONFLICT (instrument_id) DO UPDATE"
                " SET price_eur = excluded.price_eur, quote_currency = excluded.quote_currency,"
                " venue = excluded.venue, source = excluded.source, as_of = excluded.as_of"
            ),
            {
                "instrument_id": instrument_id,
                "price_eur": price_eur,
                "quote_currency": quote_currency,
                "venue": venue,
                "source": source,
                "as_of": as_of,
            },
        )


def last_known(engine: Engine, instrument_id: int) -> Row | None:
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT instrument_id, price_eur, quote_currency, venue, source, as_of"
                " FROM security_price WHERE instrument_id = :instrument_id"
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
                "INSERT INTO security_daily_close (instrument_id, close_date, price_eur, source)"
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
                    "SELECT close_date, price_eur, source FROM security_daily_close"
                    " WHERE instrument_id = :instrument_id"
                    " AND close_date BETWEEN :start AND :end"
                    " ORDER BY close_date"
                ),
                {"instrument_id": instrument_id, "start": start, "end": end},
            ).all()
        )
