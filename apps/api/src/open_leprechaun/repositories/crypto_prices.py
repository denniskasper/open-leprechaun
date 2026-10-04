"""Writes and reads over the stored crypto prices (ticket 18).

`crypto_price` is the last known price per Instrument — one row a fresh quote
overwrites, because it answers "what was it worth when someone last knew",
not "what has it ever been worth". `crypto_daily_close` is history: one close
per Instrument and day, first stored wins, so a backfill re-run can never
silently shift a figure a chart already showed.
"""

from collections.abc import Iterable
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import Engine, Row, text

from open_leprechaun.repositories.stances import UNBARRED_FROM_PRICING_SQL

EVENT_DAY_SQL = "(t.occurred_at AT TIME ZONE 'UTC')::date"
"""The day whose close prices an event of `transaction t` — the UTC date of
its instant, because providers bucket their history by UTC day. The same
rule as `event_day`, stated once for SQL."""


def event_day(at: datetime) -> date:
    """The day whose close prices an event at this instant."""
    if at.tzinfo is None:
        raise ValueError("An event's instant must be timezone-aware.")
    return at.astimezone(UTC).date()


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
                    f"{UNBARRED_FROM_PRICING_SQL}"
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


def close_on(engine: Engine, instrument_id: int, on: date) -> Row | None:
    """The stored close of one Instrument for one day — what values an event
    of that day (ticket 41), with the provider that answered."""
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT close_date, price_eur, source FROM crypto_daily_close"
                " WHERE instrument_id = :instrument_id AND close_date = :on"
            ),
            {"instrument_id": instrument_id, "on": on},
        ).one_or_none()


def event_legs(engine: Engine, *, batch_id: int | None = None) -> list[Row]:
    """Every leg of the ledger — or of one Import Batch — as resolving its
    historical price needs it (ticket 41): the Instrument by the identity
    attributes a provider maps (`id` is the Instrument's, so a row answers as
    the Instrument it names), whether the reference-rate universe values it
    or only the chain can — the chain's own bar included
    (`priceable_instruments`) — and the day whose close prices it, with
    whether the store already holds one. `external_id` is what the venue
    called the event, None where it was recorded by hand."""
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT t.id AS transaction_id, r.external_id, l.role,"
                    " i.id, i.type, i.symbol, i.name, i.chain, i.contract_address,"
                    " (i.family = 'cash' OR i.pegged_currency IS NOT NULL) AS reference_valued,"
                    " (i.family = 'crypto' AND i.pegged_currency IS NULL"
                    f"{UNBARRED_FROM_PRICING_SQL}) AS chain_priced,"
                    f" {EVENT_DAY_SQL} AS close_date,"
                    " c.instrument_id IS NOT NULL AS has_close"
                    " FROM transaction t"
                    " JOIN transaction_leg l ON l.transaction_id = t.id"
                    " JOIN instrument i ON i.id = l.instrument_id"
                    " LEFT JOIN imported_row r ON r.transaction_id = t.id"
                    " LEFT JOIN crypto_daily_close c"
                    f" ON c.instrument_id = i.id AND c.close_date = {EVENT_DAY_SQL}"
                    " WHERE CAST(:batch_id AS integer) IS NULL OR r.batch_id = :batch_id"
                    " ORDER BY t.id, l.id"
                ),
                {"batch_id": batch_id},
            ).all()
        )
