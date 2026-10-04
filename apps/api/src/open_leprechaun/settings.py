from datetime import timedelta
from decimal import Decimal
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from open_leprechaun import __version__
from open_leprechaun.ports.solana import PUBLIC_RPC_URL

# .../apps/api/src/open_leprechaun/settings.py -> repository root.
REPO_ROOT = Path(__file__).resolve().parents[4]


class Environment(StrEnum):
    """Which of the two instances this process is: the laptop or the server.

    Deliberately without a default: a deployment that forgot to say what it is
    should fail to start, not quietly become one of these.
    """

    development = "development"
    production = "production"


class Settings(BaseSettings):
    """Configuration, read from the environment and from the repository's .env.

    Real environment variables win over the file, so a deployment sets them
    directly and never ships a .env.
    """

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Environment = Field(description="development or production")
    database_url: str = Field(description="SQLAlchemy URL of the application database")
    application_secret: str = Field(
        min_length=16,
        description=(
            "Root secret the encryption keys for venue credentials and the "
            "two-factor secret derive from (ADR-0003, ADR-0005). Held outside the "
            "database and backed up separately; losing it means re-entering every "
            "venue credential and disabling two-factor from the host. Deliberately "
            "without a default: ciphertext under an ad-hoc key would be unrecoverable."
        ),
    )
    api_host: str = Field(default="127.0.0.1", description="Address the dev server binds to")
    api_port: int = Field(default=8000, description="Port the dev server binds to")
    release_version: str = Field(
        default=__version__,
        description="Version shown outside development, where a deployment sets it",
    )
    security_resolution_provider: str = Field(
        default="onvista",
        description=(
            "Which provider resolves a security identifier to its Listings "
            "(ticket 45). The default works without a paid plan."
        ),
    )
    security_price_provider: str = Field(
        default="onvista",
        description=(
            "Which provider quotes and backfills security prices per Listing "
            "(ticket 45). The default works without a paid plan."
        ),
    )
    reconciliation_tolerance: Decimal = Field(
        default=Decimal("0.00000001"),
        ge=0,
        description=(
            "How far a venue's stated balance may sit from the tracked one, in "
            "units of the Instrument, before reconciliation reports a gap "
            "(ticket 39). The default forgives one unit of the eighth decimal "
            "place — venue rounding — and nothing more; a run may state its own."
        ),
    )
    solana_rpc_url: str = Field(
        default=PUBLIC_RPC_URL,
        description=(
            "The Solana JSON-RPC endpoint the Address Indexer reads (ticket 38). "
            "The default is the public endpoint, which needs no key and is "
            "rate-limited; a provider's endpoint reads a long history faster."
        ),
    )
    scheduler_enabled: bool = Field(
        default=True,
        description=(
            "Whether this process runs scheduled tasks when they fall due "
            "(ticket 42). Off, tasks still run on demand through run-now; the "
            "schedules themselves are the Admin's, set in the application."
        ),
    )
    session_ttl_hours: int = Field(
        default=720,
        gt=0,
        description=(
            "Hours a login session survives after its last authenticated request. "
            "Every request renews it (sliding expiry); default thirty days."
        ),
    )

    @property
    def session_ttl(self) -> timedelta:
        return timedelta(hours=self.session_ttl_hours)


@lru_cache
def get_settings() -> Settings:
    return Settings()


SettingsDep = Annotated[Settings, Depends(get_settings)]
