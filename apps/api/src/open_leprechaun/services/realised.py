"""The realised result (ticket 54): what everything sold or closed so far
made or lost, stated apart from the unrealised result the Holdings view
states for what is still held.

It is the disposal engines' own answer, summed without their tax rules: the
private sales of coins and foreign cash (services/section23), the securities
disposals (services/security_disposals) and the closed futures positions
(ADR-0009) — each gain proceeds less basis less costs, on the same replay
and by the same valuations the tax report reads, so the portfolio and the
report cannot disagree about what a sale made. What tax law then does with a
gain — the Haltefrist, a Freigrenze, Teilfreistellung, a Vorabpauschale
already taxed, an acquisition without consideration falling outside §23 —
changes what is taxable, never what was realised, and plays no part in the
sum. The engines are still the engines: one that refuses a year's report
over a missing setting refuses here too, and says so.

A figure is stated only over what can be stated. An event whose gain awaits
a valuation is counted and left out of the sum, the count beside the figure;
a kind none of whose events state a gain is unstated, never zero; and a kind
its engine refuses — a sale no lot vouches for, a fund left unclassified —
carries the engine's own sentence instead of a figure, while the kinds
beside it still answer.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal, Protocol

from sqlalchemy import Engine

from open_leprechaun.ports.reference_rates import ReferenceRateSource
from open_leprechaun.repositories import futures as futures_repository
from open_leprechaun.repositories import lots as lots_repository
from open_leprechaun.services import futures, fx, lots, section23, security_disposals
from open_leprechaun.services.advance_lump_sums import FundValueUnsetError
from open_leprechaun.services.disposals import LotShortfallError
from open_leprechaun.services.fx import RateUnavailableError
from open_leprechaun.services.rounding import cents
from open_leprechaun.services.security_disposals import UnclassifiedSecurityError
from open_leprechaun.services.statutory import StatutoryValueUnsetError

__all__ = ["Component", "Realised", "realised"]

# What an engine may refuse over — the refusals report generation answers
# 409 for; anything else is a defect and fails the request.
_REFUSALS = (
    LotShortfallError,
    UnclassifiedSecurityError,
    StatutoryValueUnsetError,
    FundValueUnsetError,
    RateUnavailableError,
)


Kind = Literal["private_sales", "securities", "futures"]


@dataclass(frozen=True)
class Component:
    """One kind of realisation. `result_eur` sums the `stated` of its
    `events` and is None where none can state a gain or the engine refused —
    `refusal` then says why."""

    kind: Kind
    result_eur: Decimal | None
    stated: int
    events: int
    refusal: str | None = None


@dataclass(frozen=True)
class Realised:
    """Every kind, and their sum — None as soon as one kind is unstated,
    since a total over the rest would pose as the whole."""

    components: tuple[Component, ...]
    result_eur: Decimal | None
    stated: int
    events: int


def realised(engine: Engine, source: ReferenceRateSource, *, today: date) -> Realised:
    """The realised result through the current Tax Year — an event dated
    beyond it has not happened yet."""
    components = (
        _component("private_sales", lambda: _private_sales(engine, source, today.year)),
        _component("securities", lambda: _securities(engine, source, today.year)),
        _component("futures", lambda: _futures(engine, source, today)),
    )
    return Realised(
        components=components,
        result_eur=(
            None
            if any(component.result_eur is None for component in components)
            else sum((component.result_eur for component in components), cents(Decimal(0)))
        ),
        stated=sum(component.stated for component in components),
        events=sum(component.events for component in components),
    )


def _component(kind: Kind, gains: Callable[[], Iterable[Decimal | None]]) -> Component:
    try:
        every = list(gains())
    except _REFUSALS as refusal:
        return Component(kind=kind, result_eur=None, stated=0, events=0, refusal=str(refusal))
    stated = [gain for gain in every if gain is not None]
    return Component(
        kind=kind,
        result_eur=cents(sum(stated, Decimal(0))) if stated or not every else None,
        stated=len(stated),
        events=len(every),
    )


def _private_sales(
    engine: Engine, source: ReferenceRateSource, through_year: int
) -> Iterable[Decimal | None]:
    """One gain per private sale: proceeds less basis less costs over every
    consumption — exempt or not, and a lot received for nothing at the zero
    it cost, though §23 states no gain for either. None while any component
    awaits a valuation."""
    for disposal in section23.disposals_through(engine, source, through_year=through_year):
        yield _gain(disposal.consumptions)


def _securities(
    engine: Engine, source: ReferenceRateSource, through_year: int
) -> Iterable[Decimal | None]:
    """One gain per securities disposal: proceeds less basis less costs. The
    Vorabpauschale the engine deducts from the taxable gain is tax already
    paid on the same money, not less of it realised."""
    for disposal in security_disposals.disposals_through(engine, source, through_year=through_year):
        yield _gain(disposal.consumptions)


class _Consumed(Protocol):
    """What either engine states about one consumed lot slice."""

    @property
    def proceeds_eur(self) -> Decimal | None: ...
    @property
    def basis_eur(self) -> Decimal | None: ...
    @property
    def costs_eur(self) -> Decimal | None: ...


def _gain(pieces: Sequence[_Consumed]) -> Decimal | None:
    total = Decimal(0)
    for piece in pieces:
        if piece.proceeds_eur is None or piece.basis_eur is None or piece.costs_eur is None:
            return None
        total += piece.proceeds_eur - piece.basis_eur - piece.costs_eur
    return total


def _futures(engine: Engine, source: ReferenceRateSource, today: date) -> Iterable[Decimal | None]:
    """One net figure per closed position — realised result less trading
    fees plus funding — in EUR at the close, by the rule the §20 producer
    values it with (services/section20)."""
    with lots.snapshot(engine) as connection:
        instrument_rows = lots_repository.instrument_rows(connection)
        positions = futures_repository.closed_position_rows(connection)
    instruments = {row.id: row for row in instrument_rows}
    for position in positions:
        if fx.event_date(position.closed_at).year > today.year:
            continue
        yield fx.value_eur(
            engine,
            source,
            instrument=instruments[position.settlement_instrument_id],
            quantity=futures.net_figure(position),
            at=position.closed_at,
        )
