from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# .../apps/api/src/open_leprechaun/settings.py -> repository root.
REPO_ROOT = Path(__file__).resolve().parents[4]


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

    database_url: str = Field(description="SQLAlchemy URL of the application database")
    api_host: str = Field(default="127.0.0.1", description="Address the dev server binds to")
    api_port: int = Field(default=8000, description="Port the dev server binds to")


@lru_cache
def get_settings() -> Settings:
    return Settings()
