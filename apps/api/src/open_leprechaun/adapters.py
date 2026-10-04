"""The ingestion registries, as dependencies.

One mapping from venue name to the adapter instances that venue ships, one
from connector name to the CSV connector, and one from chain name to the
Address Indexer — each read straight from its registry (ports/venues,
ports/connectors, ports/indexers), so adding a venue, a connector or a chain
stays one implementation plus a registry entry. Exposed the way the engine is
(db.get_engine), so tests bind the app to fakes of the ports without touching
global state, and no service or router ever imports an implementation
directly.
"""

from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from open_leprechaun.ports.address_indexer import AddressIndexer
from open_leprechaun.ports.connectors import CONNECTORS
from open_leprechaun.ports.csv_connector import CsvConnector
from open_leprechaun.ports.exchange import ExchangeAdapter
from open_leprechaun.ports.indexers import indexers
from open_leprechaun.ports.venues import VENUES
from open_leprechaun.settings import get_settings


@lru_cache
def get_exchange_adapters() -> Mapping[str, Sequence[ExchangeAdapter]]:
    return {venue.venue: venue.adapters for venue in VENUES.values()}


ExchangeAdaptersDep = Annotated[
    Mapping[str, Sequence[ExchangeAdapter]], Depends(get_exchange_adapters)
]


def get_csv_connectors() -> Mapping[str, CsvConnector]:
    return CONNECTORS


CsvConnectorsDep = Annotated[Mapping[str, CsvConnector], Depends(get_csv_connectors)]


@lru_cache
def get_address_indexers() -> Mapping[str, AddressIndexer]:
    return indexers(solana_rpc_url=get_settings().solana_rpc_url)


AddressIndexersDep = Annotated[Mapping[str, AddressIndexer], Depends(get_address_indexers)]
