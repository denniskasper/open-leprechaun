"""Historical price resolution on import (ticket 41). A committed row that
states no price of its own gets the price that applied at its timestamp — the
close of its day, through the crypto price chain (ADR-0018) — so an income
valuation and the cost basis resting on it are real rather than backfilled
from today's price.

A row states its own price when one whole side of an exchange is cash or a
stablecoin and the other side is a single position: the reference-rate
universe values the money (ADR-0017), and the one thing exchanged for it
needs nothing. Several positions against one sum need their relative market
values, so they are priced like anything else. Everything else the chain alone can price — income
received, a spend, a crypto-for-crypto trade, a bare movement, and every fee
paid in a coin — wants the close of its day.

What the chain answers is kept in the daily-close store with the provider
that answered and the day it represents, first stored wins. A row the chain
could not price is **listed in the import result**, never defaulted to zero:
zero is a statement about value, and an inflow nothing prices is unknown,
never immaterial (ADR-0012). The resolution runs after the batch has landed,
so no provider's named failure can cost the import itself. A gap is the
absence of a close, so it settles itself: the scheduled price update runs the
same resolution over the whole ledger, and a backfill of the Instrument does
it by hand — the store, not this run, is what the valuation rule reads
(`fx.value_eur`). An event of the current UTC day waits that way too: its day
has no close yet.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from itertools import groupby

from sqlalchemy import Engine, Row

from open_leprechaun.ports.crypto_prices import CryptoPriceProvider
from open_leprechaun.ports.reference_rates import ReferenceRateSource
from open_leprechaun.repositories import crypto_prices as stored_prices
from open_leprechaun.services import crypto_prices
from open_leprechaun.services.price_reports import ProviderCondition

_SIDES = ("in", "out")


@dataclass(frozen=True)
class PriceSources:
    """What resolving a historical price takes: the crypto price chain in its
    documented order, and the reference rates a non-EUR close converts by."""

    providers: Sequence[CryptoPriceProvider]
    rate_source: ReferenceRateSource


@dataclass(frozen=True)
class UnpricedInstrument:
    """An Instrument with no close for an event's day — by id as well as
    symbol, since two tokens may share a ticker (ADR-0010)."""

    instrument_id: int
    symbol: str


@dataclass(frozen=True)
class UnpricedRow:
    """One imported row nothing could price: which Instruments of it have no
    close for the day it happened."""

    external_id: str
    instruments: tuple[UnpricedInstrument, ...]


@dataclass(frozen=True)
class Resolution:
    """What resolving a batch's prices left open: the rows still unpriced,
    and what any failing provider's failure was — so a gap reads as a rate
    limit to wait out or an Instrument nothing covers, never the same."""

    unpriced: tuple[UnpricedRow, ...] = ()
    conditions: tuple[ProviderCondition, ...] = ()


def resolve_batch(engine: Engine, sources: PriceSources, batch_id: int) -> Resolution:
    """Price every leg of the batch that wants a close and has none, then
    answer which rows the chain left unpriced."""
    conditions, awaiting = _resolve(engine, sources, batch_id=batch_id)
    unpriced: dict[str, dict[int, UnpricedInstrument]] = {}
    for leg in awaiting:
        unpriced.setdefault(leg.external_id, {})[leg.id] = UnpricedInstrument(leg.id, leg.symbol)
    return Resolution(
        unpriced=tuple(
            UnpricedRow(external_id, tuple(instruments.values()))
            for external_id, instruments in unpriced.items()
        ),
        conditions=conditions,
    )


def resolve_ledger(engine: Engine, sources: PriceSources) -> tuple[ProviderCondition, ...]:
    """The same resolution over every event of the ledger, however it was
    recorded — what a scheduled price update runs, so a gap an import left
    behind (a rate limit, or an event of a day that had no close yet) is
    settled without anyone asking."""
    conditions, _ = _resolve(engine, sources, batch_id=None)
    return conditions


def _resolve(
    engine: Engine, sources: PriceSources, *, batch_id: int | None
) -> tuple[tuple[ProviderCondition, ...], list[Row]]:
    """Ask the chain for every close wanted and not held, answering the
    providers' named failures and the legs still awaiting a close after."""
    wanted: dict[int, tuple[Row, set[date]]] = {}
    for leg in _awaiting(engine, batch_id):
        # A leg row answers as the Instrument it names: `leg.id` is its id.
        wanted.setdefault(leg.id, (leg, set()))[1].add(leg.close_date)
    if not wanted:
        return (), []
    conditions = crypto_prices.resolve_daily_closes(
        engine, sources.providers, sources.rate_source, list(wanted.values())
    )
    return conditions, _awaiting(engine, batch_id)


def _awaiting(engine: Engine, batch_id: int | None) -> list[Row]:
    """The legs that want a close the store does not hold."""
    legs = stored_prices.event_legs(engine, batch_id=batch_id)
    return [
        leg
        for _, event in groupby(legs, key=lambda leg: leg.transaction_id)
        for leg in _wanting_a_close(list(event))
        if not leg.has_close
    ]


def _wanting_a_close(legs: list[Row]) -> list[Row]:
    """The legs of one event only the chain can price. A fee always is its
    own cost; the exchanged sides want nothing where the event states its
    price."""
    taken, given = ([leg for leg in legs if leg.role == side] for side in _SIDES)
    states_its_price = any(
        money and len(other) == 1 and all(leg.reference_valued for leg in money)
        for money, other in ((taken, given), (given, taken))
    )
    return [leg for leg in legs if leg.chain_priced and (leg.role == "fee" or not states_its_price)]
