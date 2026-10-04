from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from open_leprechaun import API_PREFIX, __version__
from open_leprechaun.db import get_engine
from open_leprechaun.routers import (
    address_imports,
    aggregates,
    auth,
    column_mappings,
    connections,
    corporate_actions,
    csv_imports,
    futures,
    health,
    holdings,
    imports,
    instruments,
    meta,
    platforms,
    prices,
    reports,
    scheduled_tasks,
    securities,
    statutory,
    transactions,
    transfer_matches,
)
from open_leprechaun.scheduler import Scheduler
from open_leprechaun.settings import get_settings
from open_leprechaun.tasks import process_scheduled_tasks


@asynccontextmanager
async def _scheduling(app: FastAPI) -> AsyncIterator[None]:
    """Answer scheduled tasks for as long as the app serves (ticket 42),
    unless this instance was told not to."""
    if not get_settings().scheduler_enabled:
        yield
        return
    scheduler = Scheduler(get_engine, process_scheduled_tasks)
    scheduler.start()
    try:
        yield
    finally:
        scheduler.stop()


def create_app(*, scheduling: bool = False) -> FastAPI:
    """The API. `scheduling` starts the background scheduler alongside it —
    only the served app asks for that, so an app built for a test never runs
    real work behind the test's back."""
    app = FastAPI(
        lifespan=_scheduling if scheduling else None,
        title="Open Leprechaun API",
        version=__version__,
        summary="A self-hosted ledger that produces German tax figures",
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=f"{API_PREFIX}/redoc",
    )

    @app.exception_handler(RequestValidationError)
    async def validation_error_without_the_body(
        request: Request, refused: RequestValidationError
    ) -> JSONResponse:
        """FastAPI's default 422 echoes the offending input back — for a
        malformed credential request that would return the secret material it
        carried (ADR-0003: never, in any form). Only what was wrong and where
        survives; the values themselves never leave."""
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {"type": error["type"], "loc": error["loc"], "msg": error["msg"]}
                    for error in refused.errors()
                ]
            },
        )

    # health, meta and auth's own entry points are the public routes; anything
    # else added here takes open_leprechaun.auth's AdminDep, which is what
    # keeps production closed.
    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(meta.router, prefix=API_PREFIX)
    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(address_imports.router, prefix=API_PREFIX)
    app.include_router(aggregates.router, prefix=API_PREFIX)
    app.include_router(column_mappings.router, prefix=API_PREFIX)
    app.include_router(connections.router, prefix=API_PREFIX)
    app.include_router(corporate_actions.router, prefix=API_PREFIX)
    app.include_router(csv_imports.router, prefix=API_PREFIX)
    app.include_router(futures.router, prefix=API_PREFIX)
    app.include_router(holdings.router, prefix=API_PREFIX)
    app.include_router(imports.router, prefix=API_PREFIX)
    app.include_router(instruments.router, prefix=API_PREFIX)
    app.include_router(platforms.router, prefix=API_PREFIX)
    app.include_router(prices.router, prefix=API_PREFIX)
    app.include_router(reports.router, prefix=API_PREFIX)
    app.include_router(scheduled_tasks.router, prefix=API_PREFIX)
    app.include_router(securities.router, prefix=API_PREFIX)
    app.include_router(statutory.router, prefix=API_PREFIX)
    app.include_router(transactions.router, prefix=API_PREFIX)
    app.include_router(transfer_matches.router, prefix=API_PREFIX)
    return app


app = create_app(scheduling=True)
