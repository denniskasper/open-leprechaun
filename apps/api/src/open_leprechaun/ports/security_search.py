"""The security search port (ticket 44): the seam the Admin's add-a-security
search goes through. A query — ISIN, WKN, ticker or name — answers candidates
carrying everything creation needs: the identifiers, the display metadata,
the primary listing, and — for a fund — whatever classification the provider
can vouch for.

A candidate's classification is a prefill, never a verdict: it arrives marked
with its provider source, stays overridable, and is absent where the provider
cannot say — never guessed. Failures reuse the price port's vocabulary: a
rate limit is its own named condition, distinct from an outage.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SecurityCandidate:
    """One provider result, shaped for creation: ISIN as identity, WKN and
    ticker as lookup aliases, and the primary listing's venue and currency."""

    isin: str
    wkn: str | None
    ticker: str | None
    name: str
    # The ledger's security types: share, etf, fund, bond or certificate.
    type: str
    currency: str | None
    venue: str | None
    # The Teilfreistellung category the provider vouches for, if any — one of
    # the schema's fund categories, prefilled with source 'provider', always
    # overridable (§20 InvStG).
    fund_category: str | None
    distribution_policy: str | None


class SecuritySearchProvider(Protocol):
    @property
    def name(self) -> str: ...

    def search(self, query: str) -> list[SecurityCandidate]:
        """Candidates for an ISIN, WKN, ticker or name — empty when the
        provider knows nothing matching, which is a normal answer."""
        ...
