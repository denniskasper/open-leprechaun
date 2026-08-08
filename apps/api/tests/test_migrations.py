"""The migration harness: one linear chain, walkable in both directions.

Schema changes ship only as migrations, and `alembic upgrade head` — wrapped as
`pnpm db:migrate` — is the only upgrade path. These tests hold regardless of
what the chain contains, so they need no editing as it grows.
"""

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from open_leprechaun.seed import seed


def test_the_chain_has_exactly_one_head(alembic_config):
    heads = ScriptDirectory.from_config(alembic_config).get_heads()

    assert len(heads) == 1


def test_the_chain_walks_up_to_head_and_back_down_to_base_with_data_present(alembic_config, engine):
    """The seed is applied at head, so from the first real step onward the
    down path is proven against data, never just an empty schema."""
    head = ScriptDirectory.from_config(alembic_config).get_current_head()

    command.upgrade(alembic_config, "head")
    assert _current_revision(engine) == head
    seed(engine)

    command.downgrade(alembic_config, "base")
    assert _tables_besides_alembics_own(engine) == set()

    command.upgrade(alembic_config, "head")
    assert _current_revision(engine) == head


def _current_revision(engine):
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _tables_besides_alembics_own(engine):
    return set(inspect(engine).get_table_names()) - {"alembic_version"}
