"""Prepare the end-to-end run's own database: create it if missing, migrate and seed it.

Playwright runs this with the API's interpreter before it starts the API, with
DATABASE_URL pointing at the end-to-end database (see playwright.config.ts) —
so a test run never writes into the development data. Migrations run here as
a release step runs them in deployment; the seed is idempotent, and gives the
journeys that need its fixtures (USD, BTC) something to arrange over.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, make_url, text

from open_leprechaun import seed
from open_leprechaun.settings import get_settings

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "api" / "alembic.ini"

url = make_url(get_settings().database_url)
maintenance = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
try:
    with maintenance.connect() as connection:
        exists = connection.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": url.database},
        ).scalar_one_or_none()
        if exists is None:
            # The name comes from configuration, and CREATE DATABASE takes no
            # bind parameters.
            connection.execute(text(f'CREATE DATABASE "{url.database}"'))
finally:
    maintenance.dispose()

config = Config(str(ALEMBIC_INI))
config.set_main_option("sqlalchemy.url", url.render_as_string(hide_password=False))
command.upgrade(config, "head")
seed.main()
