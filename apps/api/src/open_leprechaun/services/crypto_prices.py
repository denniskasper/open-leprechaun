"""Crypto prices through a fallback chain (ticket 18).

Providers are tried in the chain's documented order. Each answers for the
Instruments it can identify; the ones it cannot fall through to the next
provider, so no provider-specific identifier being absent ever excludes an
Instrument from pricing. A provider that fails contributes a named condition
— rate-limited or outage, never conflated — and the chain moves on.

What a provider answers becomes the stored last-known price, with its source
and the instant it represents. When every provider has failed or passed over
an Instrument, that stored price is served clearly labelled stale — its age
and source on display — and an Instrument nothing has ever priced is named
unpriced, never valued at zero. Staleness is therefore always a statement
about named Instruments, not a blanket outage.

A provider quoting a currency other than EUR is converted by the
reference-rate rule of the quote's event date (ADR-0017) before serving or
storing, the same rule every other foreign-currency amount follows.
"""

from collections.abc import Sequence
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import Engine

from open_leprechaun.ports.crypto_prices import (
    CryptoPriceProvider,
    DailyClose,
    ProviderOutageError,
    RateLimitedError,
)
from open_leprechaun.ports.reference_rates import ReferenceRateSource
from open_leprechaun.repositories import crypto_prices as stored_prices
from open_leprechaun.services import fx
from open_leprechaun.services.price_reports import (
    BackfillReport,
    NamedInstrument,
    PricedInstrument,
    PriceReport,
    ProviderCondition,
    in_eur,
    served_from_store,
)

__all__ = [
    "BackfillReport",
    "NamedInstrument",
    "PriceReport",
    "PricedInstrument",
    "ProviderCondition",
    "backfill_daily_closes",
    "refresh_prices",
]


def refresh_prices(
    engine: Engine,
    providers: Sequence[CryptoPriceProvider],
    rate_source: ReferenceRateSource,
) -> PriceReport:
    """Price every priceable crypto Instrument through the chain, store what
    the providers answered, and serve the rest from the store labelled stale."""
    remaining = {row.id: row for row in stored_prices.priceable_instruments(engine)}
    fresh: dict[int, PricedInstrument] = {}
    conditions: list[ProviderCondition] = []
    for provider in providers:
        if not remaining:
            break
        try:
            quotes = provider.quotes(list(remaining.values()))
        except RateLimitedError:
            conditions.append(ProviderCondition(provider.name, "rate_limited"))
            continue
        except ProviderOutageError:
            conditions.append(ProviderCondition(provider.name, "outage"))
            continue
        for quote in quotes:
            instrument = remaining.get(quote.instrument_id)
            if instrument is None:
                continue
            price_eur = in_eur(
                engine, rate_source, price=quote.price, currency=quote.currency, at=quote.as_of
            )
            if price_eur is None:
                # No answer after all — the Instrument stays in the running
                # for the next provider, or for the store's stale price.
                continue
            remaining.pop(quote.instrument_id)
            stored_prices.store_quote(
                engine,
                instrument_id=instrument.id,
                price_eur=price_eur,
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
    providers: Sequence[CryptoPriceProvider],
    rate_source: ReferenceRateSource,
    *,
    instrument_id: int,
    start: date,
    end: date,
) -> BackfillReport | None:
    """Populate the chosen range of daily closes from the first provider in
    the chain with history for the Instrument. None when no such Instrument
    is priceable by the chain at all."""
    instrument = next(
        (row for row in stored_prices.priceable_instruments(engine) if row.id == instrument_id),
        None,
    )
    if instrument is None:
        return None
    conditions: list[ProviderCondition] = []
    for provider in providers:
        try:
            closes = provider.daily_closes(instrument, start, end)
        except RateLimitedError:
            conditions.append(ProviderCondition(provider.name, "rate_limited"))
            continue
        except ProviderOutageError:
            conditions.append(ProviderCondition(provider.name, "outage"))
            continue
        if not closes:
            continue
        # Newest first: a non-EUR close converts by its own date's reference
        # rate, and descending order lets each fetched rate window cover the
        # dates that follow instead of fetching one window per day. A close
        # that is no answer — non-positive, or unconvertible just now — is
        # skipped rather than stored wrong or allowed to fail the backfill.
        converted = (
            (close.close_date, _close_in_eur(engine, rate_source, close))
            for close in sorted(closes, key=lambda close: close.close_date, reverse=True)
        )
        stored = stored_prices.store_daily_closes(
            engine,
            instrument.id,
            source=provider.name,
            closes=[(close_date, price) for close_date, price in converted if price is not None],
        )
        return BackfillReport(stored=stored, source=provider.name, conditions=tuple(conditions))
    return BackfillReport(stored=0, source=None, conditions=tuple(conditions))


def _close_in_eur(
    engine: Engine, rate_source: ReferenceRateSource, close: DailyClose
) -> Decimal | None:
    return in_eur(
        engine,
        rate_source,
        price=close.price,
        currency=close.currency,
        at=datetime.combine(close.close_date, time(12, 0), tzinfo=fx.BERLIN),
    )
