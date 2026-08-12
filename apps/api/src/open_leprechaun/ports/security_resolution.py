"""The identifier-resolution port (ticket 45): the seam that maps a security
identifier — ISIN, WKN or ticker — to the Listings a provider knows for it,
venue and quote currency each. A separate port from pricing because no
single free-tier provider does both well; the two are configured
independently and may name different providers.

An identifier the provider knows nothing for answers an empty list, which is
a normal answer — manual entry covers what no provider resolves. Failures
reuse the crypto price port's vocabulary: a rate limit is its own named
condition, distinct from an outage.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ResolvedListing:
    """One market the provider knows the security to trade on, shaped for
    creating a Listing: venue and quote currency."""

    venue: str
    quote_currency: str


class SecurityResolutionProvider(Protocol):
    @property
    def name(self) -> str: ...

    def listings(self, identifier: str) -> list[ResolvedListing]:
        """Every Listing the provider knows for the identifier — empty when
        it knows none, which is a normal answer."""
        ...
