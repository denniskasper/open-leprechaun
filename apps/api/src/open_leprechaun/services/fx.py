"""FX conversion by the euro reference rate (ticket 17, ADR-0017).

One rule for every foreign-currency amount: convert by the euro foreign
exchange reference rate of the **event date** — the Europe/Berlin calendar
date of the event's instant, the same clock that buckets tax years — never by
a rate of report time. The ECB publishes no rate on weekends and TARGET
closing days; such a date resolves to the **most recent publication on or
before it**, at most PUBLICATION_LOOKBACK_DAYS back, which covers the longest
TARGET closure run with room to spare. A gap beyond that bound is an error
naming the currency and date, never a silently stale figure.

Reproducibility is the store's immutability: a conversion fetches only when
the store holds no answer for the event date itself — neither a published
rate nor a checked absence — and a stored row is never overwritten, so
re-running a conversion years later reproduces the same figure exactly,
whatever the source would answer today. An absence is only recorded for dates
already past in Berlin: the current day's publication may simply not exist
yet, and a conversion made before it appears must not lock the fallback in
for events that come after it.

Rates are held as published — units of currency per one euro — so the EUR
value is the amount divided by the rate, at Decimal's default precision.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Protocol
from zoneinfo import ZoneInfo

from sqlalchemy import Engine

from open_leprechaun.ports.reference_rates import ReferenceRateSource
from open_leprechaun.repositories import reference_rates

BERLIN = ZoneInfo("Europe/Berlin")

# The longest run of days without a publication is four — Easter's Friday
# through Monday, and Christmas 2025's Thursday through Sunday. Seven keeps a
# margin without ever letting a real data gap resolve to a stale rate.
PUBLICATION_LOOKBACK_DAYS = 7


class RateUnavailableError(Exception):
    """No publication within the lookback — the conversion cannot be made,
    rather than being made with a stale or invented rate."""


@dataclass(frozen=True)
class ConvertedAmount:
    """A converted figure together with what reproduces it: the rate used and
    the date that rate represents — stored alongside the amount wherever a
    conversion is persisted."""

    amount_eur: Decimal
    rate: Decimal
    rate_date: date


class CarriesPeg(Protocol):
    """Anything that says which currency it pegs — a repository row or an
    overview alike."""

    @property
    def pegged_currency(self) -> str | None: ...


def reference_rate_currency(instrument: CarriesPeg) -> str | None:
    """The currency whose daily reference rate values this Instrument — None
    when it is not a stablecoin. The routing rule the price chain (ticket 18)
    consults before any crypto provider: provider coverage of stablecoins is
    poor, and an unpriced disposal manufactures a phantom loss."""
    return instrument.pegged_currency


def event_date(at: datetime) -> date:
    """The Europe/Berlin calendar date of an instant — the date whose rate a
    conversion uses, by the same clock that buckets tax years."""
    if at.tzinfo is None:
        raise ValueError("An event's instant must be timezone-aware.")
    return at.astimezone(BERLIN).date()


def convert(
    engine: Engine,
    source: ReferenceRateSource,
    *,
    amount: Decimal,
    currency: str,
    at: datetime,
) -> ConvertedAmount:
    """`amount` of `currency` in EUR, by the reference rate of the event date.

    The euro itself converts by identity — the reference-rate universe quotes
    other currencies against it, and a caller resolving a peg should not need
    to special-case a euro stablecoin.
    """
    on = event_date(at)
    if currency == "EUR":
        return ConvertedAmount(amount_eur=amount, rate=Decimal(1), rate_date=on)
    floor = on - timedelta(days=PUBLICATION_LOOKBACK_DAYS)
    if not reference_rates.covered(engine, currency=currency, on=on):
        _fetch_window(engine, source, currency=currency, floor=floor, on=on)
    row = reference_rates.latest_on_or_before(engine, currency=currency, on=on, floor=floor)
    if row is None:
        raise RateUnavailableError(
            f"No {currency} reference rate published on or up to"
            f" {PUBLICATION_LOOKBACK_DAYS} days before {on.isoformat()}."
        )
    return ConvertedAmount(amount_eur=amount / row.rate, rate=row.rate, rate_date=row.rate_date)


def _fetch_window(
    engine: Engine, source: ReferenceRateSource, *, currency: str, floor: date, on: date
) -> None:
    """Fill the store for [floor, on]: publications as published, and a
    checked absence for every already-past day the source answered nothing
    for — so the store, not the source, answers next time."""
    published = source.daily_rates(currency, floor, on)
    reference_rates.store(engine, published)
    final_through = min(on, datetime.now(BERLIN).date() - timedelta(days=1))
    published_dates = {rate.rate_date for rate in published}
    reference_rates.record_absences(
        engine,
        currency=currency,
        dates=[
            day
            for offset in range((final_through - floor).days + 1)
            if (day := floor + timedelta(days=offset)) not in published_dates
        ],
    )
