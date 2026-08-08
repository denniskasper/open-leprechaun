"""The development server: `pnpm dev:api` runs this.

Deployments run uvicorn directly against `open_leprechaun.main:app`; only the
reloading dev server needs to read its host and port from configuration.
"""

from pathlib import Path

import uvicorn

from open_leprechaun.settings import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "open_leprechaun.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
        reload_dirs=[str(Path(__file__).resolve().parent)],
    )


if __name__ == "__main__":
    main()
