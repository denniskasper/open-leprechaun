"""The application's crypto price chain (ticket 18), as a dependency.

This tuple is the documented order: CoinGecko first — it quotes EUR directly
and covers the most instruments — then DefiLlama, quoting USD, converted by
the reference-rate rule. One chain per process, built on first use — exposed
the way the engine is (db.get_engine), so tests can bind the app to fakes of
the port without touching global state.
"""

from collections.abc import Sequence
from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from open_leprechaun.ports.coingecko import CoinGeckoProvider
from open_leprechaun.ports.crypto_prices import CryptoPriceProvider
from open_leprechaun.ports.defillama import DefiLlamaProvider
from open_leprechaun.rates import ReferenceRateSourceDep
from open_leprechaun.services.import_prices import PriceSources


@lru_cache
def get_crypto_price_chain() -> tuple[CryptoPriceProvider, ...]:
    return (CoinGeckoProvider(), DefiLlamaProvider())


CryptoPriceChainDep = Annotated[Sequence[CryptoPriceProvider], Depends(get_crypto_price_chain)]


def get_price_sources(
    chain: CryptoPriceChainDep, rate_source: ReferenceRateSourceDep
) -> PriceSources:
    """What an import resolves historical prices through (ticket 41) — the
    chain and the rate source, each taken through its own dependency, so a
    test that binds either to a fake gets imports that drive the fake."""
    return PriceSources(providers=chain, rate_source=rate_source)


PriceSourcesDep = Annotated[PriceSources, Depends(get_price_sources)]
