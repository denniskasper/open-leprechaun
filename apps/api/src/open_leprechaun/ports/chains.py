"""The ledger's names for chains, and the spellings venues use for them.

A venue names the network a transfer moved on in its own words — OKX writes
`USDC-Solana` or `USDT-TRC20`, Coinbase `solana`. A port reads its venue's
label into the ledger's chain here, the same name an Address Indexer and a
Deployment use (ADR-0032). A label not listed is no chain stated, never a
guess.
"""

# Every spelling, folded to lowercase, of each chain the ledger names.
_SPELLINGS: dict[str, frozenset[str]] = {
    "ethereum": frozenset({"ethereum", "eth", "erc20"}),
    "solana": frozenset({"solana", "sol", "spl"}),
    "base": frozenset({"base"}),
    "bitcoin": frozenset({"bitcoin", "btc"}),
    "bsc": frozenset({"bsc", "bep20", "bnb smart chain", "binance smart chain"}),
    "polygon": frozenset({"polygon", "matic", "polygon pos"}),
    "arbitrum": frozenset({"arbitrum", "arbitrum one"}),
    "optimism": frozenset({"optimism", "op mainnet"}),
    "avalanche": frozenset({"avalanche", "avalanche c-chain", "avax c-chain", "avaxc"}),
    "tron": frozenset({"tron", "trc20", "trx"}),
}
_CHAIN_OF = {spelling: chain for chain, spellings in _SPELLINGS.items() for spelling in spellings}


def chain_named(label: str | None) -> str | None:
    """The ledger's chain a venue's network label names, or None."""
    if not label:
        return None
    return _CHAIN_OF.get(label.strip().lower())
