# 03 — Migrations and seed harness

**What to build:** Schema changes ship only as migrations, and a developer can populate a realistic database with one command. Upgrading a deployed instance never means editing the database by hand.

**Blocked by:** 01

**Status:** ready-for-agent

- [x] Migrations are linear with no branching heads; one command is the only upgrade path
- [x] Every migration is tested up and down against a seeded database in CI
- [x] A migration that cannot be reversed says so explicitly and documents the manual reversal
- [x] A seed command populates realistic data and refuses to run outside development
- [x] Running the seed twice leaves the same state as running it once
- [x] The seed grows with later tickets; at this point it need only prove idempotency

## Comments

Implemented. Alembic 1.19.0, invoked only through pnpm: `pnpm db:migrate` upgrades to head (the
one upgrade path), `pnpm db:revision -- -m "…"` generates a revision, `pnpm db:seed` migrates and
then seeds. The conventions live in `apps/api/migrations/README.md`.

How each criterion is held:

- **Linearity** is a test, not a habit: `test_migrations.py` asserts exactly one head, so a second
  branch fails the suite before it can land.
- **Up and down against a seeded database** is a chain walk (`base ⇄ head ⇄ base ⇄ head`) with the
  seed applied at head, run by `pnpm test:api`. "In CI" lands with ticket 05, which runs that
  command; the test needs no change then.
- **Irreversible migrations** are a documented convention rather than a mechanism: `downgrade()`
  raises `NotImplementedError` with the manual reversal spelled out, and the walk test turns back
  above it. The revision template carries the reminder so no author has to know it in advance.
- **The seed** is a registry of idempotent steps applied in one transaction (a failed run leaves
  nothing). The registry is empty at this point — the tickets that create the first tables (09,
  10) add the first steps — so idempotency is proven two ways: injected-step tests exercise the
  runner against a probe table today, and a schema-generic run-twice-and-compare-every-table test
  gains teeth automatically as real steps land.

Deviations and decisions worth recording:

- **`ENVIRONMENT` arrives here, not with ticket 04.** The seed's development-only guard needs to
  know what the instance is, so settings now carry `development | integration | production` —
  deliberately with no default, so a deployment that forgot to say what it is fails to start
  rather than quietly becoming something. Existing `.env` files need the new line (documented in
  `.env.example`); ticket 04 builds the auth posture and the badge on this same variable.
- **The chain root is an empty revision.** No table is due yet, and creating one early would
  trespass on the tickets that own the schema. The root exists so the chain has an explicit
  beginning and every later revision names a parent.
- **The seed refuses via exit code and stderr**, proven at the command seam
  (`python -m open_leprechaun.seed` in a subprocess), so the guard is tested where a mistyped
  command would actually hit it.
- **Autogenerate is not wired to any metadata yet** (`target_metadata = None` in `env.py`); the
  ticket that introduces the first SQLAlchemy models points it at their metadata.
- **`pnpm db:migrate` is the development upgrade path**; it starts the local Postgres container
  first, which a deployed instance has no business doing. The release step (ticket 06) invokes
  the same underlying command — `python -m alembic -c alembic.ini upgrade head` — from the deploy
  pipeline, per the spec's "migrations run as a release step, not at application startup".
- **Alembic's offline `--sql` mode is explicitly refused** in `env.py` rather than half-wired:
  nothing in the spec needs SQL-script generation, and a clear refusal beats a mode that was
  never tested.

Post-review fixes: the development-run seed test migrates before seeding, so it stays
order-independent once real steps land, and the walk test's docstring no longer claims data is
present before any seed step exists.
