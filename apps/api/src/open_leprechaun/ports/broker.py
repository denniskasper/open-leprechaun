"""The broker adapter port (ticket 48, ADR-0008, ADR-0025): the seam a
broker's API is confined behind — a different shape of source than an
exchange, so a different port.

What differs is what a record can say. An exchange names an asset by its own
symbol, which is a hint the ledger must resolve; a broker names a security by
its **ISIN**, which is the ledger's own identity for it (ADR-0010), so a
security the ledger has never seen can arrive flagged for review instead of
refusing the sync. And a broker settles in the Depot's currency whatever the
security is priced in, so its records carry the amount as it was priced, the
currency it was priced in and the rate the broker applied — stated, never
converted here.

As on every port: authentication, pagination, rate limits, timezone and units
are absorbed inside the adapter; what comes out are Normalized records. An
adapter never touches the database, never converts to EUR and never computes
tax. Each kind is tested and synced alone and stamps its own per-kind
provenance (ADR-0004).

A Normalized Position is stated apart from every record that lands: it has
one consumer, Reconciliation, and is never a substitute for a transaction —
a snapshot can say that something is held, not what it cost or when it came.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

# The records and promises both account-authenticating ports share: one
# credential shape, one failure, and the two records that mean the same thing
# at an exchange and at a broker.
from open_leprechaun.ports.exchange import (
    AdapterError,
    Credentials,
    NormalizedCashMovement,
    NormalizedPosition,
)


@dataclass(frozen=True)
class NormalizedSecurity:
    """How a broker names a security: the ISIN is its identity, the symbol
    and name are display labels and nothing more.

    An API always states the ISIN. A statement may not — `isin` is None
    where a file names a paper by its ticker alone, and the symbol is then a
    resolution hint the ledger must answer before the record can land, never
    an identity (ADR-0010)."""

    isin: str | None
    symbol: str
    name: str


@dataclass(frozen=True)
class NormalizedFee:
    """One charge the broker took with a trade, in the currency it was
    charged in. `charged_against` says which side of the trade it was a cost
    of — the security (a commission, a stamp duty, a transaction tax) or the
    cash (a currency-conversion fee, the cost of acquiring the currency
    rather than of the trade it enabled) — and the fee inherits that side's
    regime."""

    name: str
    amount: Decimal
    currency: str
    charged_against: Literal["security", "cash"]


@dataclass(frozen=True)
class NormalizedOriginalAmount:
    """A trade as it was priced, where that was not the currency it settled
    in: the amount, its currency — in whole units, a venue's pence or cents
    already normalised — and `fx_rate`, the rate the broker applied, as units
    of that currency per one unit of the settlement currency: the rate the
    venue states where that reproduces the trade's own amounts, the one
    those amounts imply otherwise."""

    amount: Decimal
    currency: str
    fx_rate: Decimal


@dataclass(frozen=True)
class NormalizedSecurityTrade:
    """A security bought or sold against cash. `settled_amount` is what the
    cash balance moved by for the security itself, in the currency the Depot
    settled in, every fee stated apart.

    `original` states the trade as it was priced, None where it was priced
    in the currency it settled in."""

    external_id: str
    occurred_at: datetime
    security: NormalizedSecurity
    side: Literal["buy", "sell"]
    quantity: Decimal
    settled_amount: Decimal
    settlement_currency: str
    original: NormalizedOriginalAmount | None = None
    fees: tuple[NormalizedFee, ...] = ()


@dataclass(frozen=True)
class NormalizedDividend:
    """Income from capital paid into the Depot: `amount` is the net that
    arrived, in `currency`. `kind` says what it is — a dividend names the
    security that paid it; interest on uninvested cash names none.

    Everything else is what the broker states beyond the net, None meaning
    "the venue did not say", never a default: the gross before anything was
    withheld, in the currency it was declared in; a foreign withholding tax
    with the country that withheld it, which travel together or not at all;
    and the German tax a withholding broker took at source, split into its
    components. Every withheld amount is in the currency of `amount`
    (ADR-0022)."""

    external_id: str
    occurred_at: datetime
    kind: Literal["dividend", "interest"]
    amount: Decimal
    currency: str
    security: NormalizedSecurity | None = None
    gross_amount: Decimal | None = None
    gross_currency: str | None = None
    foreign_withholding: Decimal | None = None
    source_country: str | None = None
    kapitalertragsteuer: Decimal | None = None
    solidarity_surcharge: Decimal | None = None
    church_tax: Decimal | None = None


@dataclass(frozen=True)
class NormalizedAccountFee:
    """A standalone cost of the Depot itself — custody, account maintenance —
    with no trade to attach to."""

    external_id: str
    occurred_at: datetime
    amount: Decimal
    currency: str


@dataclass(frozen=True)
class PassedOver:
    """An event the venue states that is not a transaction this port can
    express — a split, a spin-off, a delivery free of payment. It is named so
    the Admin records it by hand, never landed and never silently dropped."""

    external_id: str
    occurred_at: datetime
    description: str


@dataclass(frozen=True)
class CoveredPeriod:
    """The span of history one pull actually read. `start` is None where the
    venue served the Depot's history from its beginning."""

    start: datetime | None
    end: datetime


@dataclass(frozen=True)
class BrokerHarvest:
    """Everything one broker kind pulled in one sync, and the period it
    covers. Deliberately no field for a Normalized Position: a snapshot
    travels through `normalized_positions` alone, so nothing that lands
    records can ever be handed one."""

    covered: CoveredPeriod
    trades: tuple[NormalizedSecurityTrade, ...] = ()
    dividends: tuple[NormalizedDividend, ...] = ()
    cash_movements: tuple[NormalizedCashMovement, ...] = ()
    account_fees: tuple[NormalizedAccountFee, ...] = ()
    passed_over: tuple[PassedOver, ...] = ()


class BrokerAdapter(Protocol):
    """One adapter kind of one broker. `test` proves the credentials open the
    venue and answers a human sentence; `pull` fetches everything reachable
    within the adapter's own lookback cap and reports the period it covered;
    `normalized_positions` states what is held right now — a security by its
    ISIN, cash by its currency — for Reconciliation alone. All raise
    AdapterError and nothing else on failure."""

    @property
    def kind(self) -> str: ...

    # The declared capability (ADR-0008): how far back the venue actually
    # reaches, in days — None where its history is unbounded.
    @property
    def lookback_days(self) -> int | None: ...

    def test(self, credentials: Credentials) -> str: ...

    def pull(self, credentials: Credentials) -> BrokerHarvest: ...

    def normalized_positions(self, credentials: Credentials) -> tuple[NormalizedPosition, ...]: ...


__all__ = [
    "AdapterError",
    "BrokerAdapter",
    "BrokerHarvest",
    "CoveredPeriod",
    "Credentials",
    "NormalizedAccountFee",
    "NormalizedCashMovement",
    "NormalizedDividend",
    "NormalizedFee",
    "NormalizedOriginalAmount",
    "NormalizedPosition",
    "NormalizedSecurity",
    "NormalizedSecurityTrade",
    "PassedOver",
]
