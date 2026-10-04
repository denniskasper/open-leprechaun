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

from collections.abc import Collection, Sequence
from datetime import UTC, date, datetime, time
from decimal import Decimal

from sqlalchemy import Engine

from open_leprechaun.ports.crypto_prices import (
    CryptoPriceProvider,
    DailyClose,
    PriceableInstrument,
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
    "resolve_daily_closes",
]


OUTAGE_PATIENCE = 3
"""How many history requests in a row a provider may fail before one
resolution stops asking it — enough to tell an Instrument it does not know
from a provider that is down, without a timeout per Instrument."""


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
        stored = _store_closes(engine, rate_source, instrument.id, provider.name, closes)
        return BackfillReport(stored=stored, source=provider.name, conditions=tuple(conditions))
    return BackfillReport(stored=0, source=None, conditions=tuple(conditions))


def resolve_daily_closes(
    engine: Engine,
    providers: Sequence[CryptoPriceProvider],
    rate_source: ReferenceRateSource,
    wanted: Sequence[tuple[PriceableInstrument, Collection[date]]],
) -> tuple[ProviderCondition, ...]:
    """Fill the store with the close of each wanted day, per Instrument
    (ticket 41). Unlike a backfill, which takes the first provider with any
    history, a day one provider left open falls through to the next — the
    chain's own rule, applied per day. One request per Instrument and
    provider, spanning the days still open; whatever else that range answers
    is kept like any backfill's.

    Nothing is returned about success: the store is the answer, and a day
    still absent from it afterwards is one nothing could price. A rate limit
    is the provider's word for the whole run, so it is not asked again; an
    outage may be one Instrument's alone — an unknown contract answers like
    one — so the provider is asked on, until OUTAGE_PATIENCE failures in a
    row say it is the provider that is down. Whatever else a provider raises
    — a malformed answer, say — is its outage too: this runs after an import
    has landed, and no provider may fail what is already written."""
    conditions: dict[ProviderCondition, None] = {}
    paused: set[str] = set()
    outages_in_a_row: dict[str, int] = {}
    for instrument, days in wanted:
        missing = set(days)
        for provider in providers:
            if not missing:
                break
            if provider.name in paused:
                continue
            start, end = min(missing), max(missing)
            try:
                closes = provider.daily_closes(instrument, start, end)
            except RateLimitedError:
                paused.add(provider.name)
                conditions[ProviderCondition(provider.name, "rate_limited")] = None
                continue
            # Broad on purpose — see the docstring: nothing may escape.
            except Exception:
                conditions[ProviderCondition(provider.name, "outage")] = None
                outages_in_a_row[provider.name] = outages_in_a_row.get(provider.name, 0) + 1
                if outages_in_a_row[provider.name] >= OUTAGE_PATIENCE:
                    paused.add(provider.name)
                continue
            outages_in_a_row[provider.name] = 0
            _store_closes(engine, rate_source, instrument.id, provider.name, closes)
            missing -= {
                row.close_date
                for row in stored_prices.daily_closes(engine, instrument.id, start=start, end=end)
            }
    return tuple(conditions)


def _store_closes(
    engine: Engine,
    rate_source: ReferenceRateSource,
    instrument_id: int,
    source: str,
    closes: Sequence[DailyClose],
) -> int:
    """Keep a provider's closes in EUR, answering how many were new.

    Newest first: a non-EUR close converts by its own date's reference rate,
    and descending order lets each fetched rate window cover the dates that
    follow instead of fetching one window per day. A close that is no answer
    — non-positive, or unconvertible just now — is skipped rather than stored
    wrong or allowed to fail the run. Nor is the current UTC day's: it has
    no close yet, and the first stored close wins forever, so a provider's
    latest intraday point must never be frozen as one."""
    today = datetime.now(UTC).date()
    converted = (
        (close.close_date, _close_in_eur(engine, rate_source, close))
        for close in sorted(closes, key=lambda close: close.close_date, reverse=True)
        if close.close_date < today
    )
    return stored_prices.store_daily_closes(
        engine,
        instrument_id,
        source=source,
        closes=[(close_date, price) for close_date, price in converted if price is not None],
    )


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
