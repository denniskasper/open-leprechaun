"""Security prices through the configured market-data provider (ticket 45).

The provider is asked once, for the Listing each Instrument's price source
names. What it answers becomes the stored last-known price, with its source,
venue and the instant it represents. When the provider fails or passes over
a Listing — or nothing names a price source at all — the stored price is
served clearly labelled stale, its age and source on display, and an
Instrument nothing has ever priced is named unpriced, never valued at zero.
Staleness is therefore always a statement about named Instruments, not a
blanket outage.

A provider quoting a currency other than EUR is converted by the
reference-rate rule of the quote's event date (ADR-0017) before serving or
storing, the same rule every other foreign-currency amount follows.
"""

from datetime import date, datetime, time

from sqlalchemy import Engine

from open_leprechaun.ports.crypto_prices import ProviderOutageError, RateLimitedError
from open_leprechaun.ports.reference_rates import ReferenceRateSource
from open_leprechaun.ports.security_prices import SecurityPriceProvider
from open_leprechaun.repositories import security_prices as stored_prices
from open_leprechaun.services import fx
from open_leprechaun.services.price_reports import (
    BackfillReport,
    PricedInstrument,
    PriceReport,
    ProviderCondition,
    in_eur,
    served_from_store,
)


def refresh_prices(
    engine: Engine,
    provider: SecurityPriceProvider,
    rate_source: ReferenceRateSource,
) -> PriceReport:
    """Price every priceable security through its price-source Listing, store
    what the provider answered, and serve the rest from the store labelled
    stale — or named unpriced."""
    remaining = {row.id: row for row in stored_prices.priceable_securities(engine)}
    listings = stored_prices.price_source_listings(engine)
    fresh: dict[int, PricedInstrument] = {}
    conditions: list[ProviderCondition] = []
    quotes = []
    if listings:
        try:
            quotes = provider.quotes(listings)
        except RateLimitedError:
            conditions.append(ProviderCondition(provider.name, "rate_limited"))
        except ProviderOutageError:
            conditions.append(ProviderCondition(provider.name, "outage"))
    for quote in quotes:
        instrument = remaining.get(quote.instrument_id)
        if instrument is None:
            continue
        price_eur = in_eur(
            engine, rate_source, price=quote.price, currency=quote.currency, at=quote.as_of
        )
        if price_eur is None:
            # No answer after all — the store speaks for the Instrument.
            continue
        remaining.pop(quote.instrument_id)
        stored_prices.store_quote(
            engine,
            instrument_id=instrument.id,
            price_eur=price_eur,
            quote_currency=quote.currency,
            venue=quote.venue,
            source=provider.name,
            as_of=quote.as_of,
        )
        fresh[instrument.id] = PricedInstrument(
            instrument_id=instrument.id,
            symbol=instrument.symbol,
            name=instrument.name,
            status="fresh",
            price_eur=price_eur,
            source=provider.name,
            as_of=quote.as_of,
        )
    entries = list(fresh.values()) + [
        served_from_store(instrument, stored_prices.last_known(engine, instrument.id))
        for instrument in remaining.values()
    ]
    entries.sort(key=lambda entry: (entry.symbol, entry.instrument_id))
    return PriceReport(prices=tuple(entries), conditions=tuple(conditions))


def backfill_daily_closes(
    engine: Engine,
    provider: SecurityPriceProvider,
    rate_source: ReferenceRateSource,
    *,
    instrument_id: int,
    start: date,
    end: date,
) -> BackfillReport | None:
    """Populate the chosen range of daily closes through the price-source
    Listing. None when no priceable security names one — nothing can vouch
    for which market's history would be fetched."""
    listing = next(
        (
            row
            for row in stored_prices.price_source_listings(engine)
            if row.instrument_id == instrument_id
        ),
        None,
    )
    if listing is None:
        return None
    try:
        closes = provider.daily_closes(listing, start, end)
    except RateLimitedError:
        return BackfillReport(
            stored=0, source=None, conditions=(ProviderCondition(provider.name, "rate_limited"),)
        )
    except ProviderOutageError:
        return BackfillReport(
            stored=0, source=None, conditions=(ProviderCondition(provider.name, "outage"),)
        )
    if not closes:
        return BackfillReport(stored=0, source=None, conditions=())
    # Newest first: a non-EUR close converts by its own date's reference
    # rate, and descending order lets each fetched rate window cover the
    # dates that follow instead of fetching one window per day. A close that
    # is no answer — non-positive, or unconvertible just now — is skipped
    # rather than stored wrong or allowed to fail the backfill.
    converted = (
        (
            close.close_date,
            in_eur(
                engine,
                rate_source,
                price=close.price,
                currency=close.currency,
                at=datetime.combine(close.close_date, time(12, 0), tzinfo=fx.BERLIN),
            ),
        )
        for close in sorted(closes, key=lambda close: close.close_date, reverse=True)
    )
    stored = stored_prices.store_daily_closes(
        engine,
        instrument_id,
        source=provider.name,
        closes=[(close_date, price) for close_date, price in converted if price is not None],
    )
    return BackfillReport(stored=stored, source=provider.name, conditions=())
