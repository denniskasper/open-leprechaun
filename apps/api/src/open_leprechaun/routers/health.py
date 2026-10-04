from collections.abc import Sequence
from contextlib import suppress
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import AwareDatetime, BaseModel

from open_leprechaun.auth import AdminDep
from open_leprechaun.db import EngineDep
from open_leprechaun.market_data import UnresolvedSecurityPricesDep
from open_leprechaun.prices import CryptoPriceChainDep
from open_leprechaun.services import fx, health, scheduled_tasks
from open_leprechaun.services.health import (
    ConfiguredProvider,
    Feed,
    HealthReport,
    HealthStatus,
    ProviderState,
    check_health,
)
from open_leprechaun.settings import SettingsDep
from open_leprechaun.tasks import ScheduledTasksDep

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["up", "down"]

    @classmethod
    def of(cls, health: HealthStatus) -> HealthResponse:
        return cls(
            status="ok" if health.healthy else "degraded",
            database="up" if health.database_up else "down",
        )


@router.get(
    "/health",
    summary="Report whether the service and its database are answering",
    response_model=HealthResponse,
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": HealthResponse,
            "description": "The service is running but its database cannot be reached",
        }
    },
)
def read_health(response: Response, engine: EngineDep) -> HealthResponse:
    health = check_health(engine)
    if not health.healthy:
        # The body still describes what is wrong, so a caller reads it either way.
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse.of(health)


class AffectedInstrumentResponse(BaseModel):
    id: int
    symbol: str
    name: str


class ProviderHealthResponse(BaseModel):
    name: str
    feeds: Feed
    # A rate limit is its own state, never an outage; `never_asked` until
    # something on this instance has asked the provider.
    state: ProviderState
    last_success_at: AwareDatetime | None
    last_error_at: AwareDatetime | None
    last_error: str | None
    # The Instruments the latest price refresh left without a fresh price
    # while this provider was failing — empty when it answers.
    affected_instruments: list[AffectedInstrumentResponse]


class KindHealthResponse(BaseModel):
    adapter_kind: str
    ok: bool
    last_success_at: AwareDatetime | None
    last_error_at: AwareDatetime | None
    last_error: str | None


class ConnectionHealthResponse(BaseModel):
    id: int
    label: str
    venue: str
    last_sync_at: AwareDatetime | None
    kinds: list[KindHealthResponse]


class TaskHealthResponse(BaseModel):
    key: str
    name: str
    enabled: bool
    running: bool
    last_started_at: AwareDatetime | None
    last_finished_at: AwareDatetime | None
    outcome: Literal["ok", "failed"] | None
    error: str | None
    # None while the task is disabled; in the past when a fire is overdue.
    next_due_at: AwareDatetime | None


class StorageResponse(BaseModel):
    database_bytes: int
    crypto_daily_closes: int
    security_daily_closes: int
    reference_rates: int


class HealthReportResponse(BaseModel):
    checked_at: AwareDatetime
    providers: list[ProviderHealthResponse]
    connections: list[ConnectionHealthResponse]
    tasks: list[TaskHealthResponse]
    scheduler_enabled: bool
    storage: StorageResponse

    @classmethod
    def of(cls, report: HealthReport) -> HealthReportResponse:
        return cls.model_validate(report, from_attributes=True)


def _configured_providers(
    chain: CryptoPriceChainDep, security_prices: UnresolvedSecurityPricesDep
) -> list[ConfiguredProvider]:
    """Every data provider this instance asks, in the order it asks them.
    A security price provider configuration names wrongly is no provider at
    all — the task that needs it says so in its own failure."""
    providers = [ConfiguredProvider(provider.name, "crypto_prices") for provider in chain]
    with suppress(ValueError):
        providers.append(ConfiguredProvider(security_prices().name, "security_prices"))
    providers.append(ConfiguredProvider(fx.REFERENCE_RATE_PROVIDER, "reference_rates"))
    return providers


@router.get(
    "/health/report",
    summary="Whether the figures are fresh: every data provider, Connection and"
    " scheduled task on its own, and what the store holds",
    response_model=HealthReportResponse,
)
def read_health_report(
    admin: AdminDep,
    engine: EngineDep,
    settings: SettingsDep,
    tasks: ScheduledTasksDep,
    providers: Annotated[Sequence[ConfiguredProvider], Depends(_configured_providers)],
) -> HealthReportResponse:
    return HealthReportResponse.of(
        health.report(
            engine,
            providers=providers,
            tasks=tasks,
            scheduler_enabled=settings.scheduler_enabled,
            now=scheduled_tasks.utc_now(),
        )
    )
