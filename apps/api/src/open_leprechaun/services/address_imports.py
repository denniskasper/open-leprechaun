"""One public address through the import framework (ticket 38, ADR-0008):
the indexer answers what moved at the address, this service names each asset
by the identity the chain stated, and the framework's own evaluation
(services/imports) alone decides what enters — preview first, commit as a
separate act.

Nothing here resolves a symbol. A chain states what an asset is — its own
coin, or a token's contract — so every leg carries that identity (ADR-0010)
and the framework resolves it or creates the Instrument. One it has never
seen therefore arrives unacknowledged: the unsolicited inflow waits in the
inbox and mints no lot until the Admin has looked (ADR-0012).

The provenance source is the chain and the address ("solana:7xKX…"), so the
Account's one authoritative source names exactly which address feeds it — a
second address may reconcile there but may not write.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace

from sqlalchemy import Engine

from open_leprechaun.ports.address_indexer import (
    AddressHistory,
    AddressIndexer,
    AddressRejectedError,
    ChainAsset,
    IndexerError,
    NormalizedAddressTransfer,
    NormalizedNetworkFee,
)
from open_leprechaun.services import imports
from open_leprechaun.services.import_prices import PriceSources
from open_leprechaun.services.imports import (
    CommitRefused,
    Committed,
    ImportLeg,
    ImportRow,
    InstrumentSpec,
    Preview,
)

Indexers = Mapping[str, AddressIndexer]


@dataclass(frozen=True)
class AddressRefused:
    """What was given is not an address on the chain — the indexer's own
    sentence, safe to show."""

    sentence: str


@dataclass(frozen=True)
class IndexerFailed:
    """The chain could not be read — the indexer's own sentence. Nothing was
    evaluated, so nothing is claimed about the address."""

    sentence: str


def source_of(chain: str, address: str) -> str:
    """The provenance stamped on everything read from this address — one
    half of the deduplication key, and what the Account's authoritative-
    source declaration names."""
    return f"{chain}:{address}"


def preview(
    engine: Engine, indexers: Indexers, *, chain: str, address: str, account_id: int
) -> Preview | AddressRefused | IndexerFailed | None:
    """What committing this address's history would do, without writing
    anything. None when no indexer reads the chain. The indexer's own
    warnings lead the framework's, because what the chain could not state is
    judged first."""
    indexer = indexers.get(chain)
    if indexer is None:
        return None
    history = _history(indexer, address)
    if not isinstance(history, AddressHistory):
        return history
    evaluated = imports.evaluate(
        engine,
        source=source_of(chain, address),
        account_id=account_id,
        rows=_rows(indexer, history),
    )
    return replace(evaluated, warnings=history.warnings + evaluated.warnings)


def commit(
    engine: Engine,
    indexers: Indexers,
    *,
    prices: PriceSources,
    chain: str,
    address: str,
    account_id: int,
) -> Committed | CommitRefused | AddressRefused | IndexerFailed | None:
    """The separate act the preview leads to — the same read and the same
    rows, the framework's own commit, one reversible batch labelled with the
    address it came from."""
    indexer = indexers.get(chain)
    if indexer is None:
        return None
    history = _history(indexer, address)
    if not isinstance(history, AddressHistory):
        return history
    return imports.commit(
        engine,
        prices=prices,
        source=source_of(chain, address),
        label=f"{indexer.name} address {address}",
        account_id=account_id,
        rows=_rows(indexer, history),
    )


def _history(
    indexer: AddressIndexer, address: str
) -> AddressHistory | AddressRefused | IndexerFailed:
    try:
        return indexer.history(address)
    except AddressRejectedError as rejected:
        return AddressRefused(str(rejected))
    except IndexerError as failed:
        return IndexerFailed(str(failed))


def _rows(indexer: AddressIndexer, history: AddressHistory) -> list[ImportRow]:
    return [_transfer_row(indexer, transfer) for transfer in history.transfers] + [
        _fee_row(indexer, fee) for fee in history.fees
    ]


def _transfer_row(indexer: AddressIndexer, transfer: NormalizedAddressTransfer) -> ImportRow:
    """One transfer as the framework's own row: the movement in the role its
    direction names, and the network fee the address paid as its own leg in
    the chain's coin, charged against the movement it enabled."""
    legs: tuple[ImportLeg, ...] = (
        ImportLeg(
            role=transfer.direction,
            quantity=transfer.quantity,
            instrument=_spec(indexer, transfer.asset),
        ),
    )
    if transfer.fee_quantity:
        legs += (
            ImportLeg(
                role="fee",
                quantity=transfer.fee_quantity,
                instrument=_spec(indexer, indexer.native),
                # By position: the movement is the first and only other leg.
                charged_against=0,
            ),
        )
    return ImportRow(
        external_id=transfer.external_id,
        type=f"transfer_{transfer.direction}",
        occurred_at=transfer.occurred_at,
        legs=legs,
    )


def _fee_row(indexer: AddressIndexer, fee: NormalizedNetworkFee) -> ImportRow:
    return ImportRow(
        external_id=fee.external_id,
        type="fee",
        occurred_at=fee.occurred_at,
        legs=(
            ImportLeg(role="fee", quantity=fee.quantity, instrument=_spec(indexer, indexer.native)),
        ),
    )


def _spec(indexer: AddressIndexer, asset: ChainAsset) -> InstrumentSpec:
    """The asset by the ledger's identity attributes: the chain's coin by its
    symbol, a token by chain and contract."""
    if asset.contract_address is None:
        return InstrumentSpec(
            kind="native", symbol=asset.symbol, name=asset.name, chain=indexer.chain
        )
    return InstrumentSpec(
        kind="token",
        symbol=asset.symbol,
        name=asset.name,
        chain=indexer.chain,
        contract_address=asset.contract_address,
        pegged_currency=asset.pegged_currency,
    )
