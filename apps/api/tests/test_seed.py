"""The seed harness: development-only, idempotent, growing with the schema.

The seam is the command itself — `python -m open_leprechaun.seed`, what
`pnpm db:seed` runs — so the environment guard is proven where it matters.
"""

import os
import subprocess
import sys

import pytest
from alembic import command
from sqlalchemy import inspect, text

from open_leprechaun.seed import seed


def test_the_seed_refuses_to_run_outside_development(database_url):
    result = _run_seed(database_url, environment="production")

    assert result.returncode != 0
    assert "production" in result.stderr
    assert "development" in result.stderr


def test_the_seed_runs_in_development(alembic_config, database_url):
    # The seed presumes a migrated database — pnpm db:seed migrates first.
    command.upgrade(alembic_config, "head")

    result = _run_seed(database_url, environment="development")

    assert result.returncode == 0, result.stderr


def test_running_the_seed_twice_leaves_the_same_state_as_running_it_once(alembic_config, engine):
    """Holds the real step sequence to idempotency, whatever the schema contains."""
    command.upgrade(alembic_config, "head")

    seed(engine)
    after_one_run = _every_row_of_every_table(engine)
    seed(engine)

    assert _every_row_of_every_table(engine) == after_one_run


def test_an_idempotent_step_reapplies_without_duplicating(engine, probe_table):
    seed(engine, steps=[_probe_step])
    seed(engine, steps=[_probe_step])

    assert _rows(engine, "SELECT id, label FROM seed_probe") == [(1, "fixture")]


def test_a_failing_step_leaves_nothing_behind(engine, probe_table):
    def exploding_step(connection):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        seed(engine, steps=[_probe_step, exploding_step])

    assert _rows(engine, "SELECT id FROM seed_probe") == []


@pytest.fixture
def probe_table(engine):
    """A stand-in for the schema the seed will one day fill.

    Created directly rather than by a migration, and dropped again, so it can
    never leak into the tests that assert what the chain creates.
    """
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE seed_probe (id integer PRIMARY KEY, label text NOT NULL)")
        )
    yield
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS seed_probe"))


def _probe_step(connection):
    connection.execute(
        text("INSERT INTO seed_probe (id, label) VALUES (1, 'fixture') ON CONFLICT (id) DO NOTHING")
    )


def _rows(engine, query):
    with engine.connect() as connection:
        return [tuple(row) for row in connection.execute(text(query)).all()]


def _every_row_of_every_table(engine):
    with engine.connect() as connection:
        tables = inspect(connection).get_table_names()
        return {
            table: sorted(
                (tuple(row) for row in connection.execute(text(f'SELECT * FROM "{table}"')).all()),
                key=repr,
            )
            for table in tables
        }


def _run_seed(database_url, environment):
    return subprocess.run(
        [sys.executable, "-m", "open_leprechaun.seed"],
        env={**os.environ, "DATABASE_URL": database_url, "ENVIRONMENT": environment},
        capture_output=True,
        text=True,
    )
