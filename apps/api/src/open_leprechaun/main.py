from fastapi import FastAPI

from open_leprechaun import API_PREFIX, __version__
from open_leprechaun.routers import health


def create_app() -> FastAPI:
    app = FastAPI(
        title="Open Leprechaun API",
        version=__version__,
        summary="A self-hosted ledger that produces German tax figures",
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=f"{API_PREFIX}/redoc",
    )
    app.include_router(health.router, prefix=API_PREFIX)
    return app


app = create_app()
