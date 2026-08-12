"""The application's securities market-data providers (ticket 45), as
dependencies. Identity resolution and pricing are separate ports because no
single free-tier provider does both well; each is chosen by name in
configuration, and onvista — keyless, so it works without a paid plan —
implements both and is the default for each. One provider instance per
process, built on first use and exposed the way the engine is
(db.get_engine), so tests can bind the app to fakes of the ports without
touching global state.
"""

from collections.abc import Callable
from functools import lru_cache
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends

from open_leprechaun.ports.security_prices import SecurityPriceProvider
from open_leprechaun.ports.security_resolution import SecurityResolutionProvider
from open_leprechaun.settings import get_settings

if TYPE_CHECKING:
    from open_leprechaun.ports.onvista_market_data import OnvistaMarketDataProvider


@lru_cache
def _onvista() -> OnvistaMarketDataProvider:
    from open_leprechaun.ports.onvista_market_data import OnvistaMarketDataProvider

    return OnvistaMarketDataProvider()


# Provider name against factory, one registry per port — adding a provider
# means adding an implementation and an entry, nothing else.
RESOLUTION_PROVIDERS = {"onvista": _onvista}
PRICE_PROVIDERS = {"onvista": _onvista}


def get_security_resolution() -> SecurityResolutionProvider:
    return _configured(RESOLUTION_PROVIDERS, get_settings().security_resolution_provider)


def get_security_prices() -> SecurityPriceProvider:
    return _configured(PRICE_PROVIDERS, get_settings().security_price_provider)


def _configured[Provider](registry: dict[str, Callable[[], Provider]], name: str) -> Provider:
    try:
        return registry[name]()
    except KeyError:
        known = ", ".join(sorted(registry))
        raise ValueError(f"No market-data provider named {name!r} — one of: {known}.") from None


SecurityResolutionDep = Annotated[SecurityResolutionProvider, Depends(get_security_resolution)]
SecurityPricesDep = Annotated[SecurityPriceProvider, Depends(get_security_prices)]
