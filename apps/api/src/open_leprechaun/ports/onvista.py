"""The onvista implementation of the security search port — one query
endpoint that accepts ISIN, WKN, ticker or name alike, free of any key.

The query answers identity and display metadata; currency, primary listing
and — for a fund — the classification come from each candidate's snapshot.
A snapshot that fails degrades that one candidate to its query fields rather
than failing the search: a picker with a gap is worth more than no picker.

The classification prefill maps onvista's fund-type vocabulary onto the §20
InvStG categories only where the mapping is defensible — Aktienfonds,
Mischfonds, Immobilienfonds, and the fund types that carry no exemption. A
type outside that list prefils nothing: the value is the Admin's to state,
never a guess.
"""

import httpx

from open_leprechaun.ports.crypto_prices import (
    ProviderOutageError,
    RateLimitedError,
    fetch_json,
)
from open_leprechaun.ports.security_search import SecurityCandidate

API = "https://api.onvista.de/api/v1"

# How many candidates a search answers — each costs one snapshot request.
LIMIT = 8

# onvista's entity types against the ledger's security types. Absence means
# "not offered here" — an index, a currency pair or a derivative is skipped,
# and manual creation covers what no provider does.
ENTITY_TYPES = {"STOCK": "share", "FUND": "fund", "BOND": "bond"}

# The snapshot path each entity type answers under.
SNAPSHOT_PATHS = {"STOCK": "stocks", "FUND": "funds", "BOND": "bonds"}

# onvista's fund-type names against the §20 InvStG categories, where the
# mapping is defensible. Renten- and Geldmarktfonds carry no exemption, which
# is a statement — `sonstige` — not an absence.
FUND_CATEGORIES = {
    "Aktienfonds": "aktienfonds",
    "Mischfonds": "mischfonds",
    "Immobilienfonds": "immobilienfonds",
    "Rentenfonds": "sonstige",
    "Geldmarktfonds": "sonstige",
}

DISTRIBUTION_POLICIES = {"Thesaurierend": "accumulating", "Ausschüttend": "distributing"}


class OnvistaProvider:
    name = "onvista"

    def __init__(self, client: httpx.Client | None = None) -> None:
        # onvista answers 429 to the default python user agent regardless of
        # rate; an honest app-named one is served.
        self._client = client or httpx.Client(
            timeout=10.0, headers={"User-Agent": "open-leprechaun"}
        )

    def search(self, query: str) -> list[SecurityCandidate]:
        answer = fetch_json(
            self._client,
            f"{API}/instruments/query",
            provider="onvista",
            params={"searchValue": query, "limit": str(LIMIT)},
        )
        candidates = []
        for entry in answer.get("list", []):
            type = ENTITY_TYPES.get(entry.get("entityType"))
            if type is None or not entry.get("isin"):
                continue
            if type == "fund" and entry.get("entitySubType") == "ETF":
                type = "etf"
            candidates.append(_candidate(entry, type, self._snapshot(entry)))
        return candidates

    def _snapshot(self, entry: dict) -> dict:
        """One candidate's enrichment — an empty answer when the snapshot
        fails, degrading the candidate rather than the search."""
        try:
            return fetch_json(
                self._client,
                f"{API}/{SNAPSHOT_PATHS[entry['entityType']]}/{entry['entityValue']}/snapshot",
                provider="onvista",
            )
        except RateLimitedError, ProviderOutageError:
            return {}


def _candidate(entry: dict, type: str, snapshot: dict) -> SecurityCandidate:
    quote = snapshot.get("quote") or {}
    funds = snapshot.get("fundsDetails") or {}
    fund_type = funds.get("nameTypeFund") if type in ("etf", "fund") else None
    capitalisation = (funds.get("fundsTypeCapitalisation") or {}).get("name")
    return SecurityCandidate(
        isin=entry["isin"],
        wkn=entry.get("wkn"),
        ticker=entry.get("symbol"),
        name=entry.get("name") or entry["isin"],
        type=type,
        currency=quote.get("isoCurrency"),
        venue=(quote.get("market") or {}).get("name"),
        fund_category=FUND_CATEGORIES.get(fund_type) if fund_type else None,
        distribution_policy=DISTRIBUTION_POLICIES.get(capitalisation) if capitalisation else None,
    )
