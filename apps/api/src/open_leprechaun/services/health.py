"""What the application can say about itself.

Two answers. `check_health` is the readiness probe: is the database there at
all. `report` is the health panel (ticket 55): whether the numbers on every
other page are fresh — per data provider, per Connection and its adapter
kinds, per scheduled task, and what the store holds. The report states each
thing on its own, because that is the whole point: one provider failing is
that provider's condition and the staleness of the Instruments it names,
never an outage of everything (ADR-0018).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import Engine

from open_leprechaun.db import database_answers
from open_leprechaun.repositories import provider_status, storage
from open_leprechaun.services import connections, scheduled_tasks
from open_leprechaun.services.scheduled_tasks import Task, TaskState

Feed = Literal["crypto_prices", "security_prices", "reference_rates"]
ProviderState = Literal["ok", "rate_limited", "outage", "never_asked"]


@dataclass(frozen=True)
class HealthStatus:
    """What the service can say about its own readiness."""

    database_up: bool

    @property
    def healthy(self) -> bool:
        """Healthy means every signal is good. There is one signal so far."""
        return self.database_up


def check_health(engine: Engine) -> HealthStatus:
    return HealthStatus(database_up=database_answers(engine))


@dataclass(frozen=True)
class ConfiguredProvider:
    """A data provider this instance asks, and what it asks it for."""

    name: str
    feeds: Feed


@dataclass(frozen=True)
class AffectedInstrument:
    id: int
    symbol: str
    name: str


@dataclass(frozen=True)
class ProviderHealth:
    name: str
    feeds: Feed
    # `never_asked` until something asks; a rate limit is its own state,
    # never an outage.
    state: ProviderState
    last_success_at: datetime | None
    last_error_at: datetime | None
    last_error: str | None
    # The Instruments the latest price refresh left without a fresh price
    # while this provider was failing.
    affected_instruments: tuple[AffectedInstrument, ...]


@dataclass(frozen=True)
class KindHealth:
    adapter_kind: str
    # The kind's latest recorded result — a sync's or a test's.
    ok: bool
    last_success_at: datetime | None
    last_error_at: datetime | None
    last_error: str | None


@dataclass(frozen=True)
class ConnectionHealth:
    id: int
    label: str
    venue: str
    # When any of its kinds last recorded a result; None before the first.
    last_sync_at: datetime | None
    kinds: tuple[KindHealth, ...]


@dataclass(frozen=True)
class Storage:
    database_bytes: int
    crypto_daily_closes: int
    security_daily_closes: int
    reference_rates: int


@dataclass(frozen=True)
class HealthReport:
    checked_at: datetime
    providers: tuple[ProviderHealth, ...]
    connections: tuple[ConnectionHealth, ...]
    tasks: tuple[TaskState, ...]
    # Whether this process answers schedules at all — where it does not, a
    # next due time is when a run is owed, not when one will happen.
    scheduler_enabled: bool
    storage: Storage


def report(
    engine: Engine,
    *,
    providers: Sequence[ConfiguredProvider],
    tasks: Sequence[Task],
    scheduler_enabled: bool,
    now: datetime,
) -> HealthReport:
    return HealthReport(
        checked_at=now,
        providers=_providers(engine, providers),
        connections=_connections(engine),
        tasks=tuple(scheduled_tasks.list_tasks(engine, tasks, now=now)),
        scheduler_enabled=scheduler_enabled,
        storage=_storage(engine),
    )


def _providers(
    engine: Engine, configured: Sequence[ConfiguredProvider]
) -> tuple[ProviderHealth, ...]:
    statuses = provider_status.statuses(engine)
    affected: dict[str, list[AffectedInstrument]] = {}
    for row in provider_status.affected_instruments(engine):
        affected.setdefault(row.provider, []).append(
            AffectedInstrument(id=row.id, symbol=row.symbol, name=row.name)
        )
    listed = []
    for provider in configured:
        status = statuses.get(provider.name)
        state: ProviderState = "never_asked"
        if status is not None:
            state = status.condition or "ok"
        listed.append(
            ProviderHealth(
                name=provider.name,
                feeds=provider.feeds,
                state=state,
                last_success_at=status.last_success_at if status else None,
                last_error_at=status.last_error_at if status else None,
                last_error=status.last_error if status else None,
                # A provider answering again affects nothing, whatever an
                # earlier refresh found.
                affected_instruments=tuple(affected.get(provider.name, ()))
                if state in ("rate_limited", "outage")
                else (),
            )
        )
    return tuple(listed)


def _connections(engine: Engine) -> tuple[ConnectionHealth, ...]:
    listed = []
    for connection in connections.overview(engine):
        instants = [
            instant
            for status in connection.statuses
            for instant in (status.last_success_at, status.last_error_at)
            if instant is not None
        ]
        listed.append(
            ConnectionHealth(
                id=connection.id,
                label=connection.label,
                venue=connection.venue,
                last_sync_at=max(instants, default=None),
                kinds=tuple(
                    KindHealth(
                        adapter_kind=status.adapter_kind,
                        ok=status.last_error is None,
                        last_success_at=status.last_success_at,
                        last_error_at=status.last_error_at,
                        last_error=status.last_error,
                    )
                    for status in connection.statuses
                ),
            )
        )
    return tuple(listed)


def _storage(engine: Engine) -> Storage:
    measured = storage.measure(engine)
    return Storage(
        database_bytes=measured.database_bytes,
        crypto_daily_closes=measured.crypto_daily_closes,
        security_daily_closes=measured.security_daily_closes,
        reference_rates=measured.reference_rates,
    )
