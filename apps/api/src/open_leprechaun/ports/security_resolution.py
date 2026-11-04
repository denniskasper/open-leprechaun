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

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

# Every tax figure is stated in it, so a close quoted in it needs no
# conversion by the reference rate.
_NUMERAIRE = "EUR"


@dataclass(frozen=True)
class ResolvedListing:
    """One market the provider knows the security to trade on, shaped for
    creating a Listing: venue and quote currency — and how much of the
    security traded there over the last four weeks, in units of it, where
    the provider states that. Comparable across one security's markets only."""

    venue: str
    quote_currency: str
    traded_four_weeks: Decimal | None = None


def best_first(listings: Iterable[ResolvedListing]) -> list[ResolvedListing]:
    """The markets in the order they are worth choosing to price by: quoted in
    the numéraire first, since its closes need no conversion; then the most
    traded, since a daily close rests on its trades; a market with no stated
    volume after every one that has some. The provider's own order breaks
    ties."""
    return sorted(
        listings,
        key=lambda listing: (
            listing.quote_currency != _NUMERAIRE,
            listing.traded_four_weeks is None,
            -(listing.traded_four_weeks or 0),
        ),
    )


class SecurityResolutionProvider(Protocol):
    @property
    def name(self) -> str: ...

    def listings(self, identifier: str) -> list[ResolvedListing]:
        """Every Listing the provider knows for the identifier — empty when
        it knows none, which is a normal answer."""
        ...
