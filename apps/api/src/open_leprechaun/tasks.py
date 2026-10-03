"""The application's scheduled tasks (ticket 42), as a dependency.

The catalogue bound to this process's engine, settings, price providers and
adapter registry — each taken through its own dependency, so a test that
binds the app to fakes of those gets tasks that drive the fakes, and a test
of the scheduling itself overrides this one to hand over tasks of its own.
"""

from collections.abc import Callable, Sequence
from typing import Annotated

from fastapi import Depends, Request

from open_leprechaun.adapters import ExchangeAdaptersDep, get_exchange_adapters
from open_leprechaun.db import EngineDep, get_engine
from open_leprechaun.market_data import get_security_prices
from open_leprechaun.ports.security_prices import SecurityPriceProvider
from open_leprechaun.prices import CryptoPriceChainDep, get_crypto_price_chain
from open_leprechaun.rates import ReferenceRateSourceDep, get_reference_rate_source
from open_leprechaun.services.scheduled_tasks import Task
from open_leprechaun.services.task_catalogue import catalogue
from open_leprechaun.settings import SettingsDep, get_settings


def _security_provider(request: Request) -> Callable[[], SecurityPriceProvider]:
    """The security price provider, unresolved: naming an unknown provider in
    configuration must fail the one task that needs it when it runs, not
    every request that lists the tasks. Still read through the app's
    overrides, so a test's fake provider is the one the task drives."""
    return request.app.dependency_overrides.get(get_security_prices, get_security_prices)


def get_scheduled_tasks(
    engine: EngineDep,
    settings: SettingsDep,
    crypto_chain: CryptoPriceChainDep,
    rate_source: ReferenceRateSourceDep,
    adapters: ExchangeAdaptersDep,
    security_provider: Annotated[Callable[[], SecurityPriceProvider], Depends(_security_provider)],
) -> Sequence[Task]:
    return catalogue(
        engine=engine,
        settings=settings,
        crypto_chain=crypto_chain,
        security_provider=security_provider,
        rate_source=rate_source,
        adapters=adapters,
    )


def process_scheduled_tasks() -> Sequence[Task]:
    """The same catalogue outside a request — what the scheduler runs."""
    return catalogue(
        engine=get_engine(),
        settings=get_settings(),
        crypto_chain=get_crypto_price_chain(),
        security_provider=get_security_prices,
        rate_source=get_reference_rate_source(),
        adapters=get_exchange_adapters(),
    )


ScheduledTasksDep = Annotated[Sequence[Task], Depends(get_scheduled_tasks)]
