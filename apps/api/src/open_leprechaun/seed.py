"""Populate a development database with realistic data: `pnpm db:seed`.

The seed grows with the schema — each ticket that adds a table appends a step
here. Every step must be idempotent: running the seed twice must leave the
database exactly as one run left it, and tests/test_seed.py holds the whole
sequence to that.

It refuses to run outside development, so a mistyped command on a deployed
instance can never write fixture data into a real ledger.
"""

import sys
from collections.abc import Callable, Sequence

from sqlalchemy import Connection, Engine, create_engine

from open_leprechaun.settings import Environment, get_settings

SeedStep = Callable[[Connection], None]

STEPS: Sequence[SeedStep] = ()
"""One entry per seeded slice of the schema, in dependency order."""


def seed(engine: Engine, steps: Sequence[SeedStep] = STEPS) -> None:
    """Apply every step in one transaction, so a failed seed leaves nothing."""
    with engine.begin() as connection:
        for step in steps:
            step(connection)


def main() -> None:
    settings = get_settings()
    if settings.environment is not Environment.development:
        sys.exit(
            f"Refusing to seed: this instance is {settings.environment}, and the seed "
            "writes fixture data meant only for development."
        )
    engine = create_engine(settings.database_url)
    try:
        seed(engine)
    finally:
        engine.dispose()
    print(f"Seeded the development database ({len(STEPS)} steps).")


if __name__ == "__main__":
    main()
