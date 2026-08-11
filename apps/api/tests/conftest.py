from collections.abc import Callable, Iterator
from contextlib import ExitStack
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url

from open_leprechaun.db import get_engine
from open_leprechaun.main import create_app
from open_leprechaun.settings import Environment, Settings, get_settings

# Somewhere nothing listens, so connecting fails fast rather than hanging.
UNREACHABLE_DATABASE_URL = "postgresql+psycopg://nobody:nobody@127.0.0.1:1/nothing"

API_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def database_url() -> str:
    """A dedicated test database, created beside the development one on first use.

    Tests run against real Postgres — the queries and the migrations are part of
    what is under test, so an in-memory substitute would not prove anything.
    """
    development_url = make_url(get_settings().database_url)
    test_url = development_url.set(database=f"{development_url.database}_test")
    _create_database_if_missing(test_url)
    return test_url.render_as_string(hide_password=False)


@pytest.fixture
def alembic_config(database_url: str) -> AlembicConfig:
    """The migration chain, bound to the test database."""
    config = AlembicConfig(str(API_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture
def engine(database_url: str) -> Iterator[Engine]:
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def db(alembic_config: AlembicConfig, engine: Engine) -> Engine:
    """A migrated database with no instruments or platforms yet."""
    command.upgrade(alembic_config, "head")
    with engine.begin() as connection:
        # Transactions first: an Account or Instrument with ledger entries
        # behind it refuses to go. Legs follow their Transaction by cascade,
        # and Tax Lots follow their legs; the fingerprint alone would outlive
        # its materialisation, so it goes explicitly. Reports are frozen
        # artifacts with no foreign keys, so they go explicitly too.
        connection.execute(text("DELETE FROM report"))
        connection.execute(text("DELETE FROM input_fingerprint"))
        # Reference rates key on (currency, date) with no foreign key, so a
        # rate one test stored for today would answer another test's current-
        # value conversion.
        connection.execute(text("DELETE FROM reference_rate"))
        # Futures rows hold their Account and settlement Instrument by
        # RESTRICT; funding first, releasing its position attribution.
        connection.execute(text("DELETE FROM funding_payment"))
        connection.execute(text("DELETE FROM futures_fill"))
        connection.execute(text("DELETE FROM futures_derivation_issue"))
        connection.execute(text("DELETE FROM futures_position"))
        # The import registry before the transactions it points at: deleting a
        # Transaction under a live registry row would leave a row the schema
        # only permits as an overridden tombstone.
        connection.execute(text("DELETE FROM imported_row"))
        connection.execute(text("DELETE FROM import_batch"))
        # Saved column mappings reference nothing and nothing references
        # them; a name saved by one test must not answer another's list.
        connection.execute(text("DELETE FROM column_mapping"))
        connection.execute(text("DELETE FROM transaction"))
        # Aggregates after their member transactions; the SET NULL release
        # makes either order work, this one just deletes nothing twice.
        connection.execute(text("DELETE FROM aggregate"))
        connection.execute(text("DELETE FROM instrument"))
        # Connections before Platforms for the same reason as Accounts; their
        # per-kind status rows follow by cascade.
        connection.execute(text("DELETE FROM connection"))
        # Accounts first: a Platform still holding one refuses to go.
        connection.execute(text("DELETE FROM account"))
        connection.execute(text("DELETE FROM platform"))
    return engine


@pytest.fixture
def fresh_db(alembic_config: AlembicConfig, engine: Engine) -> Engine:
    """A database created from nothing by the whole chain — what a first
    deployment gets, before any seed or import has run."""
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    return engine


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    """The API bound to the test database."""
    yield from _client_using(engine)


@pytest.fixture
def client_without_database() -> Iterator[TestClient]:
    """The API bound to a database that cannot be reached."""
    engine = create_engine(UNREACHABLE_DATABASE_URL, connect_args={"connect_timeout": 1})
    yield from _client_using(engine)
    engine.dispose()


@pytest.fixture
def make_client() -> Iterator[Callable[..., TestClient]]:
    """A factory for clients under settings the test chooses.

    For behaviour that pivots on the environment. Unless a test passes the real
    test `engine`, these clients never reach a database — their settings point
    somewhere nothing listens. The base URL is https because production marks
    its session cookie Secure, and a cookie the client would refuse to return
    proves nothing.
    """
    stack = ExitStack()

    def make(environment: Environment, engine: Engine | None = None, **overrides) -> TestClient:
        settings = Settings(
            environment=environment,
            database_url=UNREACHABLE_DATABASE_URL,
            **overrides,
        )
        if engine is None:
            engine = create_engine(UNREACHABLE_DATABASE_URL, connect_args={"connect_timeout": 1})
            stack.callback(engine.dispose)
        app = create_app()
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_engine] = lambda: engine
        return stack.enter_context(TestClient(app, base_url="https://testserver"))

    yield make
    stack.close()


def _client_using(engine: Engine) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: engine
    with TestClient(app) as client:
        yield client


def _create_database_if_missing(url: URL) -> None:
    maintenance_engine = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with maintenance_engine.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": url.database},
            ).scalar_one_or_none()
            if exists is None:
                # The database name comes from configuration, not from a request,
                # and CREATE DATABASE takes no bind parameters.
                connection.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        maintenance_engine.dispose()
