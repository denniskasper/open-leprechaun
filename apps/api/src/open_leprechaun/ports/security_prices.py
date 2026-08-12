"""The securities pricing port (ticket 45): the seam a security's market
price comes through. Identity resolution is a separate port
(security_resolution) because no single free-tier provider does both well.

A provider is asked for the Listing each Instrument's price source names —
venue and quote currency, chosen by the Admin or vouched for by the picker —
and identifies it by the ledger's own attributes: ISIN, venue, quote
currency. A Listing the provider cannot map is simply absent from its
answer: not covered here is a normal answer the store resolves by serving
the last known price labelled stale, or naming the Instrument unpriced.

A quote records the currency and venue it was made in; converting a non-EUR
quote by the reference-rate rule (ADR-0017) is the pricing service's job,
never the port's. Failures reuse the crypto port's vocabulary: a rate limit
is its own named condition, distinct from an outage.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from open_leprechaun.ports.crypto_prices import DailyClose


class PriceableListing(Protocol):
    """What identifying a price-source Listing to a provider takes — a
    repository row or anything shaped like one."""

    @property
    def instrument_id(self) -> int: ...

    @property
    def isin(self) -> str: ...

    @property
    def venue(self) -> str: ...

    @property
    def quote_currency(self) -> str: ...


@dataclass(frozen=True)
class ListingQuote:
    instrument_id: int
    # In the listing's quote currency, exactly as answered.
    price: Decimal
    currency: str
    # The market that made the quote, as the ledger names it.
    venue: str
    # The instant the quote represents, per the provider — not fetch time.
    as_of: datetime


class SecurityPriceProvider(Protocol):
    @property
    def name(self) -> str: ...

    def quotes(self, listings: Sequence[PriceableListing]) -> list[ListingQuote]:
        """Current quotes for every Listing this provider can identify — the
        ones it cannot are absent, not errors."""
        ...

    def daily_closes(self, listing: PriceableListing, start: date, end: date) -> list[DailyClose]:
        """One close per day of [start, end] the provider has history for —
        empty when it cannot identify the Listing."""
        ...
