"""The CoinGecko implementation of the crypto price port — the chain's
primary, quoting EUR directly.

CoinGecko keys natives on its own coin ids and tokens on an asset-platform id
plus contract address; the mappings below absorb that quirk. An Instrument
absent from them is simply not covered here — the chain asks the next
provider — so no CoinGecko identifier being absent ever excludes an
Instrument from pricing. Prices decode through Decimal, never a float.

The free API answers 429 when it wants a pause; that is the rate-limit
condition, its own named thing, distinct from an outage.
"""

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any

import httpx

from open_leprechaun.ports.crypto_prices import (
    DailyClose,
    PriceableInstrument,
    Quote,
    fetch_json,
)

API = "https://api.coingecko.com/api/v3"

# CoinGecko's ids for the native coins this deployment is likely to meet.
# Extending coverage is one line here; absence means "not covered", never
# an error.
NATIVE_COIN_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "ADA": "cardano",
    "DOT": "polkadot",
    "AVAX": "avalanche-2",
    "ATOM": "cosmos",
    "XRP": "ripple",
    "LTC": "litecoin",
    "DOGE": "dogecoin",
    "TRX": "tron",
    "BNB": "binancecoin",
    "MATIC": "matic-network",
    "NEAR": "near",
}

# The ledger's chain names against CoinGecko's asset-platform ids.
CHAIN_PLATFORMS = {
    "ethereum": "ethereum",
    "solana": "solana",
    "bsc": "binance-smart-chain",
    "polygon": "polygon-pos",
    "arbitrum": "arbitrum-one",
    "optimism": "optimistic-ethereum",
    "base": "base",
    "avalanche": "avalanche",
}


class CoinGeckoProvider:
    name = "coingecko"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=10.0)

    def quotes(self, instruments: Sequence[PriceableInstrument]) -> list[Quote]:
        quotes: list[Quote] = []
        natives = {
            NATIVE_COIN_IDS[i.symbol]: i
            for i in instruments
            if i.type == "native" and i.symbol in NATIVE_COIN_IDS
        }
        if natives:
            answer = self._get(
                "/simple/price",
                params={
                    "ids": ",".join(sorted(natives)),
                    "vs_currencies": "eur",
                    "include_last_updated_at": "true",
                },
            )
            quotes += [
                quote
                for coin_id, instrument in natives.items()
                if (quote := _quote_from(answer.get(coin_id), instrument)) is not None
            ]
        by_platform: dict[str, list[PriceableInstrument]] = defaultdict(list)
        for instrument in instruments:
            if instrument.type == "token" and instrument.chain in CHAIN_PLATFORMS:
                by_platform[CHAIN_PLATFORMS[instrument.chain]].append(instrument)
        for platform, tokens in sorted(by_platform.items()):
            answer = self._get(
                f"/simple/token_price/{platform}",
                params={
                    "contract_addresses": ",".join(token.contract_address for token in tokens),
                    "vs_currencies": "eur",
                    "include_last_updated_at": "true",
                },
            )
            # Response keys echo the addresses; compare lowercased so a
            # checksum-cased echo cannot lose a quote.
            lowered = {key.lower(): value for key, value in answer.items()}
            quotes += [
                quote
                for token in tokens
                if (quote := _quote_from(lowered.get(token.contract_address.lower()), token))
                is not None
            ]
        return quotes

    def daily_closes(
        self, instrument: PriceableInstrument, start: date, end: date
    ) -> list[DailyClose]:
        if instrument.type == "native":
            coin_id = NATIVE_COIN_IDS.get(instrument.symbol)
            if coin_id is None:
                return []
            path = f"/coins/{coin_id}/market_chart/range"
        else:
            platform = CHAIN_PLATFORMS.get(instrument.chain or "")
            if platform is None:
                return []
            path = f"/coins/{platform}/contract/{instrument.contract_address}/market_chart/range"
        answer = self._get(
            path,
            params={
                "vs_currency": "eur",
                "from": str(int(datetime.combine(start, time.min, tzinfo=UTC).timestamp())),
                "to": str(int(datetime.combine(end, time.max, tzinfo=UTC).timestamp())),
            },
        )
        # Short ranges answer finer-grained points; the last point of each
        # UTC day is that day's close.
        last_per_day: dict[date, Decimal] = {}
        for millis, price in answer.get("prices", []):
            last_per_day[datetime.fromtimestamp(millis / 1000, UTC).date()] = price
        return [
            DailyClose(close_date=day, price=price, currency="EUR")
            for day, price in sorted(last_per_day.items())
            if start <= day <= end
        ]

    def _get(self, path: str, *, params: dict[str, str]) -> Any:  # noqa: ANN401
        return fetch_json(self._client, f"{API}{path}", provider="CoinGecko", params=params)


def _quote_from(answer: dict | None, instrument: PriceableInstrument) -> Quote | None:
    if answer is None or "eur" not in answer:
        return None
    # last_updated_at is the instant the quote represents; a response without
    # one can only honestly claim "now".
    as_of = (
        datetime.fromtimestamp(answer["last_updated_at"], UTC)
        if "last_updated_at" in answer
        else datetime.now(UTC)
    )
    return Quote(instrument_id=instrument.id, price=answer["eur"], currency="EUR", as_of=as_of)
