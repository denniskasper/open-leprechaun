"""The ingestion registries, as dependencies.

One mapping from venue name to the adapter instances that venue ships, and
one from connector name to the CSV connector — each read straight from its
registry (ports/venues, ports/connectors), so adding a venue or a connector
stays one implementation plus a registry entry. Exposed the way the engine is
(db.get_engine), so tests bind the app to fakes of the ports without touching
global state, and no service or router ever imports an implementation
directly.
"""

from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from open_leprechaun.ports.connectors import CONNECTORS
from open_leprechaun.ports.csv_connector import CsvConnector
from open_leprechaun.ports.exchange import ExchangeAdapter
from open_leprechaun.ports.venues import VENUES


@lru_cache
def get_exchange_adapters() -> Mapping[str, Sequence[ExchangeAdapter]]:
    return {venue.venue: venue.adapters for venue in VENUES.values()}


ExchangeAdaptersDep = Annotated[
    Mapping[str, Sequence[ExchangeAdapter]], Depends(get_exchange_adapters)
]


def get_csv_connectors() -> Mapping[str, CsvConnector]:
    return CONNECTORS


CsvConnectorsDep = Annotated[Mapping[str, CsvConnector], Depends(get_csv_connectors)]
