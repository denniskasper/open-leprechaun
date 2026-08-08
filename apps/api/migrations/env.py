"""Alembic's runtime environment.

The database URL is resolved here and nowhere else: tests inject one through
the config's `sqlalchemy.url`, and every other invocation falls back to the
application's settings — so migrations always run against the same database
the API would use.
"""

from alembic import context
from sqlalchemy import create_engine

from open_leprechaun.settings import get_settings

# Autogenerate has no target yet. The ticket that introduces the first
# SQLAlchemy models points this at their metadata.
target_metadata = None


def _database_url() -> str:
    return context.config.get_main_option("sqlalchemy.url") or get_settings().database_url


if context.is_offline_mode():
    raise SystemExit("Offline (--sql) mode is not wired up; run migrations against a database.")

engine = create_engine(_database_url())
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
