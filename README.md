# Open Leprechaun

A self-hosted ledger of everything the Admin owns — crypto on exchanges, crypto in self-custody,
futures positions, and shares, ETFs and funds at brokers — that knows German tax law well enough to
produce the figures for a tax return and shows its working for every one of them.

This is a rebuild. See [`.scratch/greenfield-v2/spec.md`](.scratch/greenfield-v2/spec.md) for the
plan, [`CONTEXT.md`](CONTEXT.md) for the domain vocabulary and [`docs/adr/`](docs/adr) for the
decisions behind it.

> **Current state: walking skeleton.** The path from Postgres through the API to the browser is
> connected and proven. Nothing else is wired yet.

## Prerequisites

- **Python 3.14**, available on your `PATH` as `python3.14`
- **Node 24** and **pnpm 11**
- **Docker** with Compose — Postgres runs in a container; everything else runs on the host so you
  can attach a debugger to the code you are changing

## Getting started

```sh
cp .env.example .env   # adjust POSTGRES_PORT and DATABASE_URL if 5434 is taken
pnpm setup             # installs web dependencies and builds apps/api/.venv
pnpm dev               # starts Postgres, the API and the web client
```

Then open <http://localhost:5173>. The page reports whether the API answered and whether it could
reach its database. The API's OpenAPI documentation is at <http://localhost:8000/api/docs>.

`pnpm setup` creates a Python virtual environment at `apps/api/.venv` and installs the pinned
requirements into it. No Python package is ever installed globally: every script invokes
`apps/api/.venv/bin/python` explicitly.

There is no Makefile. `pnpm` scripts at the repository root are the single entry point for every
task, Python ones included.

### One manual step, deliberately

This repository is public and must never carry account-derived figures. Two local git hooks guard
that — `.git/hooks/commit-msg` and `.git/hooks/pre-push`. They are **not tracked and cannot be**:
they match against the specific figures that have leaked before, so committing them would be the
leak they exist to prevent. After a fresh clone, recreate them by hand. See
[`AGENTS.md`](AGENTS.md) § Git.

## Commands

| Command             | What it does                                                     |
| ------------------- | ---------------------------------------------------------------- |
| `pnpm setup`        | Install web dependencies and create the API virtual environment   |
| `pnpm dev`          | Start Postgres, then the API and web dev servers together         |
| `pnpm dev:api`      | The API alone, reloading, on `API_HOST:API_PORT`                  |
| `pnpm dev:web`      | The web client alone, on `WEB_PORT`                               |
| `pnpm build`        | Typecheck and build the web client for production                 |
| `pnpm test`         | The API and web unit suites                                       |
| `pnpm test:api`     | pytest against a real Postgres, created on first run              |
| `pnpm test:web`     | Vitest                                                            |
| `pnpm test:e2e`     | Playwright against the running application                        |
| `pnpm typecheck`    | TypeScript, browser and Node configurations both                  |
| `pnpm lint`         | ruff check and format check                                       |
| `pnpm format`       | ruff autofix and format                                           |
| `pnpm db:up`        | Start Postgres and wait for it to be healthy                      |
| `pnpm db:down`      | Stop Postgres, keeping its data                                   |
| `pnpm db:reset`     | Destroy the Postgres volume and start fresh                       |
| `pnpm db:logs`      | Follow the Postgres log                                           |

`pnpm test:e2e` needs a Playwright browser once: `pnpm --filter @open-leprechaun/web exec
playwright install chromium`.

## Layout

```
apps/api/    FastAPI service — routers validate, services decide, repositories query
apps/web/    React client — Vite, Tailwind, TanStack Query, Zod
docs/adr/    Architectural decision records
.scratch/    Spec and implementation tickets (this repo has no hosted tracker)
```

Configuration lives in one `.env` at the root, read by Docker Compose, by the API through
pydantic-settings, and by Vite through `envDir`. Real environment variables override it, so a
deployment sets them directly and never ships a `.env`.

The web dev server proxies `/api` to the API, so the browser talks to a single origin and there is
no CORS configuration to keep in step.

## Testing

Four seams, in descending order of how much lives at each — the reasoning is in the spec.

1. **The HTTP API against a real Postgres** (`pnpm test:api`). The default seam. Ports get fakes;
   the database does not, because the queries and the migrations are part of what is under test.
   The suite creates its own `<database>_test` database on first run.
2. **The tax engine as a pure function.** Not yet built.
3. **Ports against recorded fixtures.** Not yet built.
4. **Playwright against the built application** (`pnpm test:e2e`). A few critical journeys only.
   There is deliberately no broad component-test layer.
