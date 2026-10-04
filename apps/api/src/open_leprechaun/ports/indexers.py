"""The Address Indexer registry: every chain a public address can be read on.

This is the one place chain implementations are named on the way in
(ADR-0008) — core code reads entries generically and never branches on a
chain. Adding a chain is adding an entry here; the picker on the Imports
screen, the preview and the commit follow from the entry alone.
"""

from open_leprechaun.ports.address_indexer import AddressIndexer
from open_leprechaun.ports.solana import SolanaIndexer


def indexers(*, solana_rpc_url: str) -> dict[str, AddressIndexer]:
    """Keyed by the chain name that stems every provenance source. The
    endpoints are the deployment's to choose — public ones need no key."""
    return {entry.chain: entry for entry in (SolanaIndexer(rpc_url=solana_rpc_url),)}
