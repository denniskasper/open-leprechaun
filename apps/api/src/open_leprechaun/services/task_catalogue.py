"""The scheduled tasks this application ships (ticket 42): what each one
does, the schedule it starts on, and when its run counts as failed.

Each task is existing work — the same services the manual endpoints drive —
wrapped so that it answers one sentence about what happened or raises one
about what failed. Adding a task is one more entry here; the scheduling
around it (services/scheduled_tasks) never learns what any of them do.

A price update fails only when a provider's own failure left an Instrument
without a fresh price. A provider that simply does not know an Instrument is
no failure — that Instrument would fail the task forever — and a provider
that failed while another answered for everything cost nothing.
"""

from collections.abc import Callable, Sequence

from sqlalchemy import Engine

from open_leprechaun.ports.crypto_prices import CryptoPriceProvider
from open_leprechaun.ports.reference_rates import ReferenceRateSource
from open_leprechaun.ports.security_prices import SecurityPriceProvider
from open_leprechaun.repositories import connections as connections_repository
from open_leprechaun.services import crypto_prices, exchange_sync, security_prices
from open_leprechaun.services.connections import CredentialsUnreadableError
from open_leprechaun.services.exchange_sync import Adapters
from open_leprechaun.services.price_reports import PriceReport
from open_leprechaun.services.scheduled_tasks import Task, TaskFailedError
from open_leprechaun.settings import Settings

_CONDITIONS = {"rate_limited": "is rate-limiting", "outage": "is not answering"}


def catalogue(
    *,
    engine: Engine,
    settings: Settings,
    crypto_chain: Sequence[CryptoPriceProvider],
    security_provider: Callable[[], SecurityPriceProvider],
    rate_source: ReferenceRateSource,
    adapters: Adapters,
) -> tuple[Task, ...]:
    """Every scheduled task, bound to what it works with. The security
    provider arrives as a factory: a misconfigured provider name is that one
    task's failure, not a reason no task can be listed."""

    def update_crypto_prices() -> str:
        return _price_summary(crypto_prices.refresh_prices(engine, crypto_chain, rate_source))

    def update_security_prices() -> str:
        try:
            provider = security_provider()
        except ValueError as misconfigured:
            raise TaskFailedError(str(misconfigured)) from misconfigured
        return _price_summary(security_prices.refresh_prices(engine, provider, rate_source))

    def sync_connections() -> str:
        return _sync_every_connection(engine, settings, adapters)

    return (
        Task(
            key="crypto_prices",
            name="Crypto price update",
            description="Prices every crypto Instrument through the provider chain.",
            default_cron="*/15 * * * *",
            run=update_crypto_prices,
        ),
        Task(
            key="security_prices",
            name="Security price update",
            description="Prices every security through its price-source Listing.",
            default_cron="5 * * * *",
            run=update_security_prices,
        ),
        Task(
            key="connection_sync",
            name="Connection sync",
            description="Pulls every Connection's venue history into the ledger.",
            default_cron="0 */6 * * *",
            run=sync_connections,
        ),
    )


def _price_summary(report: PriceReport) -> str:
    counts = {"fresh": 0, "stale": 0, "unpriced": 0}
    for entry in report.prices:
        counts[entry.status] += 1
    summary = f"{counts['fresh']} fresh, {counts['stale']} stale, {counts['unpriced']} unpriced."
    if report.conditions and counts["fresh"] < len(report.prices):
        providers = "; ".join(
            f"{condition.provider} {_CONDITIONS[condition.condition]}"
            for condition in report.conditions
        )
        raise TaskFailedError(f"{providers} — {summary}")
    return summary


def _sync_every_connection(engine: Engine, settings: Settings, adapters: Adapters) -> str:
    """Each Connection alone: one that cannot be synced is named in the
    failure and never keeps the next from syncing (ADR-0004)."""
    failures: list[str] = []
    connections = kinds = 0
    for connection in connections_repository.list_connections(engine):
        try:
            results = exchange_sync.sync_connection(engine, settings, adapters, connection.id)
        except CredentialsUnreadableError as sealed:
            failures.append(f"{connection.label}: {sealed}")
            continue
        except Exception as failed:
            failures.append(f"{connection.label}: {exchange_sync.failure_sentence(failed)}")
            continue
        if results is None:
            # Removed since the list was read — nothing left to sync.
            continue
        connections += 1
        for result in results:
            kinds += 1
            if result.error is not None:
                failures.append(f"{connection.label} ({result.adapter_kind}): {result.error}")
    if failures:
        raise TaskFailedError(" ".join(failures))
    return f"{kinds} adapter kinds synced across {connections} Connections."
