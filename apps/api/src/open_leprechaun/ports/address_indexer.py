"""The Address Indexer port (ticket 38, ADR-0008): the seam a public chain
is confined behind.

An indexer takes an address and answers what moved at it — nothing else goes
in. There is no credential to hand over and none to hold: a chain's history
is public, so the mode is read-only by nature rather than by permission. It
is the ingestion shape for a self-custody wallet that publishes neither an
export nor an account, and the only one that sees an unsolicited inflow,
because nothing has to be exported or signed in for the chain to state it.

What comes out are Normalized transfers in UTC and whole units. Unlike a
venue, a chain states what an asset *is* — its own coin, or the contract a
token lives at — so a transfer names its asset by that identity (ADR-0010),
never by a bare symbol. That is what lets a token the ledger has never seen
arrive as an unacknowledged Instrument rather than refusing the pull. An
indexer still never touches the database, never converts to EUR and never
computes tax; handing transfers to the import framework is the
address_imports service's job.

This port shares nothing with the exchange adapter or the CSV connector: no
credentials, no file, no venue symbols.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol


@dataclass(frozen=True)
class ChainAsset:
    """What moved, by the chain's own identity: the chain's coin when
    `contract_address` is None, otherwise the token living at that contract.
    `symbol` and `name` are labels for a human — the best the chain or the
    indexer knows — and never decide which Instrument this is."""

    symbol: str
    name: str
    contract_address: str | None = None
    # The currency a stablecoin pegs, where the indexer knows the contract.
    pegged_currency: str | None = None


@dataclass(frozen=True)
class NormalizedAddressTransfer:
    """One asset arriving at or leaving the address in one chain transaction.
    `quantity` is what moved in whole units, net of any network fee;
    `fee_quantity` is the network fee this address itself paid for the
    transaction, in the chain's coin — stated on one transfer of the
    transaction only, so it is never counted twice."""

    external_id: str
    occurred_at: datetime
    direction: Literal["in", "out"]
    asset: ChainAsset
    quantity: Decimal
    fee_quantity: Decimal | None = None


@dataclass(frozen=True)
class NormalizedNetworkFee:
    """A network fee the address paid for a transaction that moved nothing
    else at it — a failed transaction, a contract call — in the chain's
    coin."""

    external_id: str
    occurred_at: datetime
    quantity: Decimal


@dataclass(frozen=True)
class AddressHistory:
    """Everything the chain states about one address: the transfers, the
    standalone fees, and the sentences naming what the indexer saw but could
    not judge — never a silent hole."""

    transfers: tuple[NormalizedAddressTransfer, ...] = ()
    fees: tuple[NormalizedNetworkFee, ...] = ()
    warnings: tuple[str, ...] = ()


class AddressRejectedError(Exception):
    """What was given is not an address on this chain — one sentence, safe
    to show."""


class IndexerError(Exception):
    """The indexer's own failure — the chain's public endpoint not answering
    or rate-limiting, a response that would not parse, a history longer than
    the walk's budget — as one sentence safe to show."""


class AddressIndexer(Protocol):
    """One chain. `chain` is the registry key and the ledger's own name for
    the chain (what an Instrument's `chain` carries); `native` is the chain's
    coin, which network fees are paid in. `history` answers the address's
    whole reachable history, or raises AddressRejectedError or IndexerError
    and nothing else."""

    @property
    def chain(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def native(self) -> ChainAsset: ...

    # The declared capability (ADR-0008): how far back the indexer reaches,
    # in days — None where it reads the address's whole history.
    @property
    def lookback_days(self) -> int | None: ...

    def history(self, address: str) -> AddressHistory: ...
