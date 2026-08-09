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
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal

from sqlalchemy import Engine

from open_leprechaun.ports.crypto_prices import (
    CryptoPriceProvider,
    DailyClose,
    ProviderOutageError,
    Quote,
    RateLimitedError,
)
from open_leprechaun.ports.reference_rates import ReferenceRateSource
from open_leprechaun.repositories import crypto_prices as stored_prices
from open_leprechaun.services import fx


@dataclass(frozen=True)
class PricedInstrument:
    """One Instrument's answer: a current price, a stored one labelled stale,
    or the honest admission that nothing has ever priced it."""

    instrument_id: int
    symbol: str
    name: str
    status: Literal["fresh", "stale", "unpriced"]
    price_eur: Decimal | None
    source: str | None
    as_of: datetime | None


@dataclass(frozen=True)
class ProviderCondition:
    """What one provider's failure actually was — a rate limit is its own
    condition, never reported as an outage."""

    provider: str
    condition: Literal["rate_limited", "outage"]


@dataclass(frozen=True)
class PriceReport:
    prices: tuple[PricedInstrument, ...]
    conditions: tuple[ProviderCondition, ...]


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
            instrument = remaining.pop(quote.instrument_id, None)
            if instrument is None:
                continue
            price_eur = _in_eur(engine, rate_source, quote)
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
        _from_store(engine, instrument) for instrument in remaining.values()
    ]
    entries.sort(key=lambda entry: (entry.symbol, entry.instrument_id))
    return PriceReport(prices=tuple(entries), conditions=tuple(conditions))


@dataclass(frozen=True)
class BackfillReport:
    """What one backfill actually did: how many closes it added, which
    provider answered, and what any failing provider's failure was."""

    stored: int
    source: str | None
    conditions: tuple[ProviderCondition, ...]


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
        # dates that follow instead of fetching one window per day.
        stored = stored_prices.store_daily_closes(
            engine,
            instrument.id,
            source=provider.name,
            closes=[
                (close.close_date, _close_in_eur(engine, rate_source, close))
                for close in sorted(closes, key=lambda close: close.close_date, reverse=True)
            ],
        )
        return BackfillReport(stored=stored, source=provider.name, conditions=tuple(conditions))
    return BackfillReport(stored=0, source=None, conditions=tuple(conditions))


def _close_in_eur(engine: Engine, rate_source: ReferenceRateSource, close: DailyClose) -> Decimal:
    if close.currency == "EUR":
        return close.price
    return fx.convert(
        engine,
        rate_source,
        amount=close.price,
        currency=close.currency,
        at=datetime.combine(close.close_date, time(12, 0), tzinfo=fx.BERLIN),
    ).amount_eur


def _from_store(engine: Engine, instrument) -> PricedInstrument:  # noqa: ANN001
    """What remains when every provider has failed or passed over an
    Instrument: the last known price, clearly labelled stale — or the named
    admission that nothing has ever priced it."""
    stored = stored_prices.last_known(engine, instrument.id)
    if stored is None:
        return PricedInstrument(
            instrument_id=instrument.id,
            symbol=instrument.symbol,
            name=instrument.name,
            status="unpriced",
            price_eur=None,
            source=None,
            as_of=None,
        )
    return PricedInstrument(
        instrument_id=instrument.id,
        symbol=instrument.symbol,
        name=instrument.name,
        status="stale",
        price_eur=stored.price_eur,
        source=stored.source,
        as_of=stored.as_of,
    )


def _in_eur(engine: Engine, rate_source: ReferenceRateSource, quote: Quote) -> Decimal:
    """A quote in the provider's currency, expressed in EUR by the
    reference-rate rule of the quote's event date (ADR-0017)."""
    if quote.currency == "EUR":
        return quote.price
    return fx.convert(
        engine, rate_source, amount=quote.price, currency=quote.currency, at=quote.as_of
    ).amount_eur
