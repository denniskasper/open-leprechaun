from fastapi import FastAPI

from open_leprechaun import API_PREFIX, __version__
from open_leprechaun.routers import (
    auth,
    health,
    instruments,
    meta,
    platforms,
    reports,
    statutory,
    transactions,
    transfer_matches,
)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Open Leprechaun API",
        version=__version__,
        summary="A self-hosted ledger that produces German tax figures",
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=f"{API_PREFIX}/redoc",
    )
    # health, meta and auth's own entry points are the public routes; anything
    # else added here takes open_leprechaun.auth's AdminDep, which is what
    # keeps production closed.
    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(meta.router, prefix=API_PREFIX)
    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(instruments.router, prefix=API_PREFIX)
    app.include_router(platforms.router, prefix=API_PREFIX)
    app.include_router(reports.router, prefix=API_PREFIX)
    app.include_router(statutory.router, prefix=API_PREFIX)
    app.include_router(transactions.router, prefix=API_PREFIX)
    app.include_router(transfer_matches.router, prefix=API_PREFIX)
    return app


app = create_app()
