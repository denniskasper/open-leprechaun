"""The exchange adapter registry, as a dependency.

One mapping from venue name to the adapter instances that venue ships — read
straight from the venue registry (ports/venues), so adding a venue stays one
adapter plus a registry entry. Exposed the way the engine is (db.get_engine),
so tests bind the app to fakes of the port without touching global state, and
no service or router ever imports a venue's adapter directly.
"""

from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from open_leprechaun.ports.exchange import ExchangeAdapter
from open_leprechaun.ports.venues import VENUES


@lru_cache
def get_exchange_adapters() -> Mapping[str, Sequence[ExchangeAdapter]]:
    return {venue.venue: venue.adapters for venue in VENUES.values()}


ExchangeAdaptersDep = Annotated[
    Mapping[str, Sequence[ExchangeAdapter]], Depends(get_exchange_adapters)
]
