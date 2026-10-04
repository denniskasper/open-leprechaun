from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import AwareDatetime, BaseModel, PlainSerializer

from open_leprechaun.auth import AdminDep
from open_leprechaun.db import EngineDep
from open_leprechaun.rates import ReferenceRateSourceDep
from open_leprechaun.services import fx, realised, snapshots
from open_leprechaun.services.realised import Component, Realised
from open_leprechaun.services.scheduled_tasks import utc_now
from open_leprechaun.services.snapshots import Measurement

router = APIRouter(tags=["portfolio"])

# Fixed-point on the way out, as everywhere: an EUR figure is answered as a
# decimal string, never a float.
Fixed = Annotated[Decimal, PlainSerializer(lambda value: format(value, "f"), return_type=str)]


class MeasurementResponse(BaseModel):
    """The portfolio at one instant. `value_eur` and `result_eur` are null
    where something is held and none of it counts — unstated, never zero.
    Contributions and withdrawals are cumulative from the ledger's beginning;
    `unvalued_flows` counts those nothing stored could value, which stand
    outside both."""

    snapshot_date: date
    taken_at: AwareDatetime
    value_eur: Fixed | None
    positions_held: int
    positions_counted: int
    contributions_eur: Fixed
    withdrawals_eur: Fixed
    net_contributions_eur: Fixed
    result_eur: Fixed | None
    unvalued_flows: int

    @classmethod
    def of(cls, measured: Measurement) -> MeasurementResponse:
        return cls(
            **vars(measured),
            net_contributions_eur=measured.net_contributions_eur,
            result_eur=measured.result_eur,
        )


class DevelopmentResponse(BaseModel):
    snapshots: list[MeasurementResponse]
    current: MeasurementResponse


@router.get(
    "/portfolio/development",
    summary="The stored portfolio snapshots, oldest first, and the portfolio as it"
    " stands now — value beside what was contributed and withdrawn, in EUR",
    response_model=DevelopmentResponse,
)
def get_development(admin: AdminDep, engine: EngineDep) -> DevelopmentResponse:
    developed = snapshots.development(engine, now=utc_now())
    return DevelopmentResponse(
        snapshots=[MeasurementResponse.of(snapshot) for snapshot in developed.snapshots],
        current=MeasurementResponse.of(developed.current),
    )


class RealisedComponentResponse(BaseModel):
    """One kind of realisation. `result_eur` sums the `stated` of its
    `events`; null where none states a gain, or where the engine refused —
    `refusal` is then its sentence."""

    kind: Literal["private_sales", "securities", "futures"]
    result_eur: Fixed | None
    stated: int
    events: int
    refusal: str | None

    @classmethod
    def of(cls, component: Component) -> RealisedComponentResponse:
        return cls(**vars(component))


class RealisedResponse(BaseModel):
    """`result_eur` is null as soon as one kind is unstated — a sum over the
    rest would pose as the whole."""

    result_eur: Fixed | None
    stated: int
    events: int
    components: list[RealisedComponentResponse]

    @classmethod
    def of(cls, result: Realised) -> RealisedResponse:
        return cls(
            result_eur=result.result_eur,
            stated=result.stated,
            events=result.events,
            components=[RealisedComponentResponse.of(entry) for entry in result.components],
        )


@router.get(
    "/portfolio/realised",
    summary="What everything sold or closed so far made or lost, per kind, in EUR —"
    " the realised result, apart from the unrealised one Holdings states",
    response_model=RealisedResponse,
)
def get_realised(
    admin: AdminDep, engine: EngineDep, source: ReferenceRateSourceDep
) -> RealisedResponse:
    return RealisedResponse.of(realised.realised(engine, source, today=fx.event_date(utc_now())))
