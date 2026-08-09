"""The DefiLlama implementation of the crypto price port — the chain's
fallback, quoting USD; the pricing service converts by the reference-rate
rule (ADR-0017).

DefiLlama keys tokens on a chain slug plus contract address and delegates
native coins to CoinGecko's id namespace (`coingecko:bitcoin`) — the same id
table the CoinGecko port holds, imported rather than duplicated because it
factually is that provider's namespace. An Instrument neither mapping covers
is simply not covered here. Prices decode through Decimal, never a float.
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any

import httpx

from open_leprechaun.ports.coingecko import NATIVE_COIN_IDS
from open_leprechaun.ports.crypto_prices import (
    DailyClose,
    PriceableInstrument,
    Quote,
    fetch_json,
)

API = "https://coins.llama.fi"

# The ledger's chain names against DefiLlama's chain slugs.
CHAIN_SLUGS = {
    "ethereum": "ethereum",
    "solana": "solana",
    "bsc": "bsc",
    "polygon": "polygon",
    "arbitrum": "arbitrum",
    "optimism": "optimism",
    "base": "base",
    "avalanche": "avax",
}


class DefiLlamaProvider:
    name = "defillama"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=10.0)

    def quotes(self, instruments: Sequence[PriceableInstrument]) -> list[Quote]:
        keyed = {
            key: instrument
            for instrument in instruments
            if (key := _key_for(instrument)) is not None
        }
        if not keyed:
            return []
        answer = self._get(f"/prices/current/{','.join(sorted(keyed))}")
        coins = {key.lower(): value for key, value in answer.get("coins", {}).items()}
        return [
            Quote(
                instrument_id=instrument.id,
                price=coin["price"],
                currency="USD",
                as_of=datetime.fromtimestamp(coin["timestamp"], UTC),
            )
            for key, instrument in keyed.items()
            if (coin := coins.get(key.lower())) is not None and "price" in coin
        ]

    def daily_closes(
        self, instrument: PriceableInstrument, start: date, end: date
    ) -> list[DailyClose]:
        key = _key_for(instrument)
        if key is None:
            return []
        answer = self._get(
            f"/chart/{key}",
            params={
                "start": str(int(datetime.combine(start, time.min, tzinfo=UTC).timestamp())),
                "span": str((end - start).days + 1),
                "period": "1d",
            },
        )
        coins = {found.lower(): value for found, value in answer.get("coins", {}).items()}
        points = coins.get(key.lower(), {}).get("prices", [])
        last_per_day: dict[date, Decimal] = {}
        for point in points:
            last_per_day[datetime.fromtimestamp(point["timestamp"], UTC).date()] = point["price"]
        return [
            DailyClose(close_date=day, price=price, currency="USD")
            for day, price in sorted(last_per_day.items())
            if start <= day <= end
        ]

    def _get(self, path: str, *, params: dict[str, str] | None = None) -> Any:  # noqa: ANN401
        return fetch_json(self._client, f"{API}{path}", provider="DefiLlama", params=params)


def _key_for(instrument: PriceableInstrument) -> str | None:
    if instrument.type == "native":
        coin_id = NATIVE_COIN_IDS.get(instrument.symbol)
        return f"coingecko:{coin_id}" if coin_id is not None else None
    slug = CHAIN_SLUGS.get(instrument.chain or "")
    return f"{slug}:{instrument.contract_address}" if slug is not None else None
