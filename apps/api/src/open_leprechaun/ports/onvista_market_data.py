"""The onvista implementation of both market-data ports (ticket 45) — the
same keyless API the security search (ADR-0020) already speaks, so it works
without a paid plan.

Resolution and pricing both walk query → snapshot: the query maps an
identifier to onvista's entity, and the snapshot's quoteList carries every
market the security trades on with its currency, latest quote and notation.
Resolution answers those markets deduplicated; a quote is read from the
entry matching the Listing's venue and currency — one market's answer, never
whichever onvista prefers — and daily closes are fetched by that entry's
notation from the eod_history endpoint, whose parallel arrays carry one
close per trading day.

A Listing onvista cannot map — unknown identifier, or a market the snapshot
does not carry — is absent from the answer, never an invention. Failures
reuse the crypto price port's vocabulary through fetch_json.
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx

from open_leprechaun.ports.crypto_prices import DailyClose, fetch_json
from open_leprechaun.ports.security_prices import ListingQuote, PriceableListing
from open_leprechaun.ports.security_resolution import ResolvedListing

API = "https://api.onvista.de/api/v1"

# onvista's entity types with securities behind them, and the snapshot path
# each answers under — the same vocabulary the search port speaks.
SNAPSHOT_PATHS = {"STOCK": "stocks", "FUND": "funds", "BOND": "bonds"}

# The eod_history ranges onvista accepts, smallest first — the request names
# the one that covers the span, and the answer is clipped to it anyway.
RANGES = (("M1", 31), ("M3", 92), ("Y1", 366), ("Y5", 1830), ("MAX", None))


class OnvistaMarketDataProvider:
    name = "onvista"

    def __init__(self, client: httpx.Client | None = None) -> None:
        # onvista answers 429 to the default python user agent regardless of
        # rate; an honest app-named one is served.
        self._client = client or httpx.Client(
            timeout=10.0, headers={"User-Agent": "open-leprechaun"}
        )

    def listings(self, identifier: str) -> list[ResolvedListing]:
        found = self._snapshot(identifier)
        if found is None:
            return []
        _, snapshot = found
        resolved = []
        for entry in _markets(snapshot):
            listing = ResolvedListing(
                venue=entry["market"]["name"], quote_currency=entry["isoCurrency"]
            )
            if listing not in resolved:
                resolved.append(listing)
        return resolved

    def quotes(self, listings: Sequence[PriceableListing]) -> list[ListingQuote]:
        quotes = []
        snapshots: dict[str, tuple[dict, dict] | None] = {}
        for listing in listings:
            if listing.isin not in snapshots:
                snapshots[listing.isin] = self._snapshot(listing.isin)
            found = snapshots[listing.isin]
            entry = _matching(found[1], listing) if found else None
            if entry is None or entry.get("last") is None or not entry.get("datetimeLast"):
                continue
            quotes.append(
                ListingQuote(
                    instrument_id=listing.instrument_id,
                    price=Decimal(entry["last"]),
                    currency=entry["isoCurrency"],
                    venue=listing.venue,
                    as_of=datetime.fromisoformat(entry["datetimeLast"]),
                )
            )
        return quotes

    def daily_closes(self, listing: PriceableListing, start: date, end: date) -> list[DailyClose]:
        found = self._snapshot(listing.isin)
        entry = _matching(found[1], listing) if found else None
        if entry is None or not (entry.get("market") or {}).get("idNotation"):
            return []
        entity, _ = found
        answer = fetch_json(
            self._client,
            f"{API}/instruments/{entity['entityType']}/{entity['entityValue']}/eod_history",
            provider="onvista",
            params={
                "idNotation": str(entry["market"]["idNotation"]),
                "range": _range_covering((end - start).days),
                "startDate": start.isoformat(),
            },
        )
        currency = answer.get("isoCurrency") or listing.quote_currency
        closes = []
        for stamp, price in zip(
            answer.get("datetimeLast") or [], answer.get("last") or [], strict=False
        ):
            close_date = datetime.fromtimestamp(int(stamp), UTC).date()
            if price is not None and start <= close_date <= end:
                closes.append(
                    DailyClose(close_date=close_date, price=Decimal(price), currency=currency)
                )
        return closes

    def _snapshot(self, identifier: str) -> tuple[dict, dict] | None:
        """The entity behind an identifier and its snapshot — None where
        onvista knows no security entity, which is a normal answer. The
        entity travels with the snapshot because eod_history is addressed by
        it."""
        answer = fetch_json(
            self._client,
            f"{API}/instruments/query",
            provider="onvista",
            params={"searchValue": identifier, "limit": "8"},
        )
        entity = next(
            (
                entry
                for entry in answer.get("list", [])
                if entry.get("entityType") in SNAPSHOT_PATHS and entry.get("entityValue")
            ),
            None,
        )
        if entity is None:
            return None
        snapshot = fetch_json(
            self._client,
            f"{API}/{SNAPSHOT_PATHS[entity['entityType']]}/{entity['entityValue']}/snapshot",
            provider="onvista",
        )
        return entity, snapshot


def _markets(snapshot: dict) -> list[dict]:
    """Every quoteList entry that names its market and currency — falling
    back to the primary quote where the snapshot carries no list."""
    entries = (snapshot.get("quoteList") or {}).get("list") or []
    if not entries and snapshot.get("quote"):
        entries = [snapshot["quote"]]
    return [
        entry
        for entry in entries
        if (entry.get("market") or {}).get("name") and entry.get("isoCurrency")
    ]


def _matching(snapshot: dict, listing: PriceableListing) -> dict | None:
    """The market entry the Listing names — venue and quote currency both.
    The venue compares case-insensitively: a hand-entered "XETRA" must find
    onvista's "Xetra", or the security stays unpriced with no visible
    reason."""
    return next(
        (
            entry
            for entry in _markets(snapshot)
            if entry["market"]["name"].casefold() == listing.venue.casefold()
            and entry["isoCurrency"] == listing.quote_currency
        ),
        None,
    )


def _range_covering(days: int) -> str:
    for name, bound in RANGES:
        if bound is None or days <= bound:
            return name
    return "MAX"
