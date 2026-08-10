from datetime import timedelta
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from open_leprechaun import __version__

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
            "Root secret venue-credential encryption keys derive from (ADR-0003). "
            "Held outside the database and backed up separately; losing it means "
            "re-entering every venue credential. Deliberately without a default: "
            "ciphertext under an ad-hoc key would be unrecoverable."
        ),
    )
    api_host: str = Field(default="127.0.0.1", description="Address the dev server binds to")
    api_port: int = Field(default=8000, description="Port the dev server binds to")
    release_version: str = Field(
        default=__version__,
        description="Version shown outside development, where a deployment sets it",
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
