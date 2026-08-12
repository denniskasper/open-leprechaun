"""The price-report vocabulary shared by the crypto chain (ticket 18) and
the securities provider (ticket 45): what one Instrument's answer is — fresh,
stale or the honest admission that nothing has ever priced it — what one
provider's failure actually was, and the one rule turning a provider's figure
into EUR before anything is stored or served.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

import httpx
from sqlalchemy import Engine

from open_leprechaun.ports.reference_rates import ReferenceRateSource
from open_leprechaun.services import fx


class NamedInstrument(Protocol):
    """What serving an answer about an Instrument takes — a repository row or
    anything shaped like one. Naming is the point: staleness is reported per
    named Instrument, never as a blanket outage."""

    @property
    def id(self) -> int: ...

    @property
    def symbol(self) -> str: ...

    @property
    def name(self) -> str: ...


@dataclass(frozen=True)
class PricedInstrument:
    """One Instrument's answer: a current price, a stored one labelled stale,
    or the honest admission that nothing has ever priced it."""

    instrument_id: int
    symbol: str
    name: str
    status: Literal["fresh", "stale", "unpriced"]
    price_eur: Decimal | None
    source: str | None
    as_of: datetime | None


@dataclass(frozen=True)
class ProviderCondition:
    """What one provider's failure actually was — a rate limit is its own
    condition, never reported as an outage."""

    provider: str
    condition: Literal["rate_limited", "outage"]


@dataclass(frozen=True)
class PriceReport:
    prices: tuple[PricedInstrument, ...]
    conditions: tuple[ProviderCondition, ...]


@dataclass(frozen=True)
class BackfillReport:
    """What one backfill actually did: how many closes it added, which
    provider answered, and what any failing provider's failure was."""

    stored: int
    source: str | None
    conditions: tuple[ProviderCondition, ...]


class StoredPrice(Protocol):
    """What a price store's last-known row states — either family's."""

    @property
    def price_eur(self) -> Decimal: ...

    @property
    def source(self) -> str: ...

    @property
    def as_of(self) -> datetime: ...


def served_from_store(instrument: NamedInstrument, stored: StoredPrice | None) -> PricedInstrument:
    """What remains when every provider has failed or passed over an
    Instrument: the last known price, clearly labelled stale — or the named
    admission that nothing has ever priced it."""
    if stored is None:
        return PricedInstrument(
            instrument_id=instrument.id,
            symbol=instrument.symbol,
            name=instrument.name,
            status="unpriced",
            price_eur=None,
            source=None,
            as_of=None,
        )
    return PricedInstrument(
        instrument_id=instrument.id,
        symbol=instrument.symbol,
        name=instrument.name,
        status="stale",
        price_eur=stored.price_eur,
        source=stored.source,
        as_of=stored.as_of,
    )


def in_eur(
    engine: Engine,
    rate_source: ReferenceRateSource,
    *,
    price: Decimal,
    currency: str,
    at: datetime,
) -> Decimal | None:
    """A provider's figure expressed in EUR by the reference-rate rule of its
    event date (ADR-0017) — or None when the figure is no answer at all: a
    non-positive price (some providers answer 0 for a dead token, and zero is
    a statement about value this rule must never make), or a quote the
    reference-rate universe cannot state in EUR just now. None never fails
    the report; the store speaks for the Instrument instead."""
    if price <= 0:
        return None
    if currency == "EUR":
        return price
    try:
        return fx.convert(engine, rate_source, amount=price, currency=currency, at=at).amount_eur
    except fx.RateUnavailableError, httpx.HTTPError:
        return None
