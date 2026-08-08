# Migrations

Schema changes ship only as Alembic migrations. There is no other path: the
API never creates tables, and a deployed instance is never edited by hand.

## Commands

Everything goes through pnpm at the repository root:

- `pnpm db:migrate` — upgrade the database to head. The only upgrade path,
  locally and as a release step.
- `pnpm db:revision -- -m "add platform"` — generate a new revision from
  [`script.py.mako`](script.py.mako). Once models exist and `env.py` points at
  their metadata, add `--autogenerate`.
- `pnpm db:seed` — migrate, then populate development fixture data
  (`open_leprechaun/seed.py`). Refuses to run outside development.

The database URL comes from settings (`DATABASE_URL`) inside `env.py`; nothing
here carries a second copy of it.

## Rules

- **The chain is linear.** One head, no branches — enforced by
  `tests/test_migrations.py`. If two branches ever race in, merge them with
  `alembic merge` before anything else lands.
- **Every migration goes down as well as up.** The test walks the whole chain
  `base ⇄ head` against a seeded database.
- **A migration that cannot be reversed says so explicitly.** Its
  `downgrade()` raises `NotImplementedError` with the manual reversal spelled
  out step by step, and the walk in `tests/test_migrations.py` is adjusted to
  turn back above it.
