"""The exchange adapter port (ticket 35, ADR-0004, ADR-0008): the seam a
venue's API is confined behind.

An adapter is the only place that knows one exchange — authentication and
signing, pagination, rate limits, capped lookback, symbol discovery, timezone
and units are absorbed inside it. What comes out are canonical Normalized
records naming assets by the venue's symbols alone: an adapter never touches
the database, never converts to EUR and never computes tax, so it cannot know
an Instrument id or an Account. Resolving symbols against the ledger and
routing records into the futures pipeline and the import framework is the
sync service's job (services/exchange_sync).

One venue account serves several adapter kinds through one Connection
(ADR-0004); each kind is its own adapter instance, tested and synced
separately so one kind failing never hides another succeeding, and each
stamps its own per-kind provenance on what it imports.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol


class Credentials(Protocol):
    """What an adapter signs requests with — structurally the decrypted set
    the Connection service hands over, alive only for the calls it makes."""

    @property
    def key(self) -> str: ...

    @property
    def secret(self) -> str | None: ...

    @property
    def passphrase(self) -> str | None: ...


@dataclass(frozen=True)
class NormalizedTrade:
    """One Instrument exchanged for another at the venue — a spot buy or
    sell. `side` says which way the base flowed: a buy received base and gave
    quote, a sell the reverse. The fee is stated in whatever asset the venue
    charged it."""

    external_id: str
    occurred_at: datetime
    base_symbol: str
    quote_symbol: str
    side: Literal["buy", "sell"]
    base_quantity: Decimal
    quote_quantity: Decimal
    fee_symbol: str | None = None
    fee_quantity: Decimal | None = None


@dataclass(frozen=True)
class NormalizedTransfer:
    """Crypto arrived at or left the venue account. Each side is its own
    record where it happened; self-transfer matching links the two later."""

    external_id: str
    occurred_at: datetime
    direction: Literal["in", "out"]
    symbol: str
    quantity: Decimal
    fee_quantity: Decimal | None = None


@dataclass(frozen=True)
class NormalizedCashMovement:
    """Fiat entering or leaving the venue account — a deposit or a
    withdrawal, resolved within the cash family alone."""

    external_id: str
    occurred_at: datetime
    direction: Literal["in", "out"]
    currency: str
    amount: Decimal


@dataclass(frozen=True)
class NormalizedFill:
    """One futures trade execution, in the venue's own symbols — the
    repository's resolved twin (repositories/futures.NormalizedFill) carries
    the Account and settlement Instrument the sync service resolves. The
    enrichment trio and `inverse` mean exactly what they mean there: None is
    "the venue did not say", never a default."""

    external_id: str
    occurred_at: datetime
    symbol: str
    side: Literal["buy", "sell"]
    price: Decimal
    size: Decimal
    fee: Decimal
    settlement_symbol: str
    position_side: str | None = None
    reduce_only: bool | None = None
    realized: Decimal | None = None
    inverse: bool | None = None


@dataclass(frozen=True)
class NormalizedFunding:
    """One periodic financing payment: `amount` is signed in the settlement
    asset — positive received, negative paid."""

    external_id: str
    occurred_at: datetime
    symbol: str
    amount: Decimal
    settlement_symbol: str
    position_side: str | None = None


@dataclass(frozen=True)
class NormalizedPosition:
    """What the venue says is held right now — a balance or an open contract
    stated as a snapshot, never as history. Reconciliation (ticket 39) is its
    consumer: a second source may compare this against the ledger but may not
    write from it, and no derivation ever reads it (ADR-0008 rejected venues
    supplying finished positions). Part of the port's canonical vocabulary;
    no adapter emits one until reconciliation asks."""

    symbol: str
    quantity: Decimal
    as_of: datetime


@dataclass(frozen=True)
class Harvest:
    """Everything one adapter kind pulled in one sync. A kind fills the
    fields it serves and leaves the rest empty — the sync service routes by
    record, not by kind."""

    trades: tuple[NormalizedTrade, ...] = ()
    transfers: tuple[NormalizedTransfer, ...] = ()
    cash_movements: tuple[NormalizedCashMovement, ...] = ()
    fills: tuple[NormalizedFill, ...] = ()
    funding: tuple[NormalizedFunding, ...] = ()


class AdapterError(Exception):
    """An adapter's own failure — authentication, transport, a response that
    would not parse, a pagination budget exhausted — as one sentence safe to
    record and show. Never carries credential material."""


class ExchangeAdapter(Protocol):
    """One adapter kind of one venue. `test` proves the credentials open the
    venue and answers a human sentence; `pull` fetches everything reachable
    within the adapter's own lookback cap. Both raise AdapterError and
    nothing else on failure."""

    @property
    def kind(self) -> str: ...

    # The declared capability (ADR-0008): how far back the venue actually
    # reaches, in days — None where its history is unbounded. Ticket 40 turns
    # this into the coverage warning; the adapter only states the truth.
    @property
    def lookback_days(self) -> int | None: ...

    def test(self, credentials: Credentials) -> str: ...

    def pull(self, credentials: Credentials) -> Harvest: ...
