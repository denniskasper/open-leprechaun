"""The crypto price port (ticket 18): the seam a crypto Instrument's market
price comes through, tried provider by provider in a documented chain.

A provider identifies an Instrument by the ledger's own identity attributes —
chain and contract address for a token, symbol for a native coin — and maps
them to whatever identifiers it uses internally. An Instrument the provider
cannot map is simply absent from its answer: not covered here is a normal
answer the chain resolves by asking the next provider, so no provider-specific
identifier being absent can ever exclude an Instrument from pricing.

A quote carries the currency the provider quotes in; converting a non-EUR
quote by the reference-rate rule (ADR-0017) is the pricing service's job,
never the port's. Failures are named: a rate limit is its own condition,
distinct from an outage, so the chain can report what actually happened.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol


class PriceableInstrument(Protocol):
    """What identifying a crypto Instrument to a provider takes — a repository
    row or anything shaped like one."""

    @property
    def id(self) -> int: ...

    @property
    def type(self) -> str: ...

    @property
    def symbol(self) -> str: ...

    @property
    def chain(self) -> str | None: ...

    @property
    def contract_address(self) -> str | None: ...


@dataclass(frozen=True)
class Quote:
    instrument_id: int
    # In the provider's quote currency, exactly as answered.
    price: Decimal
    currency: str
    # The instant the quote represents, per the provider — not fetch time.
    as_of: datetime


@dataclass(frozen=True)
class DailyClose:
    close_date: date
    price: Decimal
    currency: str


class RateLimitedError(Exception):
    """The provider refused for now — its own named condition, never to be
    reported as a generic outage."""


class ProviderOutageError(Exception):
    """The provider failed to answer at all."""


class CryptoPriceProvider(Protocol):
    @property
    def name(self) -> str: ...

    def quotes(self, instruments: Sequence[PriceableInstrument]) -> list[Quote]:
        """Current quotes for every Instrument this provider can identify —
        the ones it cannot are absent, not errors."""
        ...

    def daily_closes(
        self, instrument: PriceableInstrument, start: date, end: date
    ) -> list[DailyClose]:
        """One close per day of [start, end] the provider has history for —
        empty when it cannot identify the Instrument."""
        ...
