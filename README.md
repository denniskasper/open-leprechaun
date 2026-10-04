# Open Leprechaun

A self-hosted ledger of everything the Admin owns — crypto on exchanges, crypto in self-custody,
futures positions, and shares, ETFs and funds at brokers — that knows German tax law well enough to
produce the figures for a tax return and shows its working for every one of them.

> **Note:** This project is under active development and provided as-is. It is not yet ready for
> production use. Use at your own risk.

See [`.scratch/roadmap/spec.md`](.scratch/roadmap/spec.md) for the plan,
[`CONTEXT.md`](CONTEXT.md) for the domain vocabulary and [`docs/adr/`](docs/adr) for the
decisions behind it.

> **Current state: feature-complete against the roadmap.** Every roadmap ticket has landed in
> code: the ledger, imports and venue adapters, the tax engine and its reports, the portfolio, the
> Admin's security settings, and a pipeline that deploys a green `main`. How the one deployed
> instance is set up is in [`docs/deployment.md`](docs/deployment.md).

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

Then open <http://localhost:5173>. The first page is the health panel — how fresh the prices,
rates and syncs are — and, if the API or its database cannot be reached, it says which. The API's OpenAPI documentation is at <http://localhost:8000/api/docs>.

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
| `pnpm setup:api`    | The API virtual environment alone — rebuild it after a requirements change |
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
| `pnpm db:migrate`   | Upgrade the database to the newest migration — the only upgrade path |
| `pnpm db:seed`      | Migrate, then populate development fixture data (development only) |
| `pnpm db:revision`  | Generate a new migration: `pnpm db:revision -- -m "message"`      |
| `pnpm db:down`      | Stop Postgres, keeping its data                                   |
| `pnpm db:reset`     | Destroy the Postgres volume and start fresh                       |
| `pnpm db:logs`      | Follow the Postgres log                                           |
| `pnpm auth:disable-two-factor` | Turn the Admin's two-factor off from the host — the anti-lockout path ([runbook](docs/runbook.md)) |

`pnpm test:e2e` needs a Playwright browser once: `pnpm --filter @open-leprechaun/web exec
playwright install chromium`.

## Layout

```
apps/api/    FastAPI service — routers validate, services decide, repositories query
apps/web/    React client — Vite, Tailwind, TanStack Query, Zod
docs/adr/    Architectural decision records
docs/agents/ Conventions agents and contributors follow — design, versioning, the tracker
docs/research/  Primary-source research the tax logic rests on
docs/runbook.md What to do when the running instance needs a hand from the host
.github/     The CI pipeline: API checks, web checks, e2e, and the deploy job
deploy/      The deployed instance: its compose stack, web server and deploy scripts
.scratch/    The finished roadmap: its spec and tickets (new work is tracked in GitHub Issues)
```

Configuration lives in one `.env` at the root, read by Docker Compose, by the API through
pydantic-settings, and by Vite through `envDir`. Real environment variables override it, so a
deployment sets them directly and never ships a `.env`. `ENVIRONMENT` selects `development` or
`production` and has deliberately no default — an instance must say what it is. There are only
these two: development happens locally, and exactly one deployed instance exists.

Schema changes ship only as migrations; see [`apps/api/migrations/`](apps/api/migrations/README.md)
for the rules (linear chain, tested up and down, irreversible migrations must say so).

The web dev server proxies `/api` to the API, so the browser talks to a single origin and there is
no CORS configuration to keep in step.

## Authentication

Development skips login entirely. In production a fresh instance serves only the first-run screen
until the admin password is set — setup runs exactly once — and one login endpoint
(`POST /api/auth/login`) then serves the browser and any future client alike: the session token
arrives both as an httpOnly cookie and in the response body, and the API accepts the cookie first,
then an `Authorization: Bearer` header. A session expires `SESSION_TTL_HOURS` (default 720 — thirty
days) after its last authenticated request; every authenticated request renews it, so renewal is
automatic while the app is in use and an idle instance logs the admin out.

Sessions are ended from the app: the header signs out of the current one, and Settings → Security
shows how many are open and signs out of all of them (`DELETE /api/auth/sessions`). The password is
changed there too — `POST /api/auth/password` takes the current password and the new one, revokes
every other session and keeps the caller's. Setup and change share one 12-character minimum.

Two-factor is optional and set up in Settings → Security: the panel shows a QR code with the raw
URI and secret beside it, and nothing is enforced until a code from the authenticator proves the
enrollment works. From then on `POST /api/auth/login` answers a password that came alone with a
401 whose body carries `"result": "code_required"`; the same request repeated with `code` issues
the unchanged token, cookie and bearer alike. Changing the password and disabling two-factor both
take a current code as well. A production instance shows a reminder on every page while
two-factor is off.

Guessing is throttled, never locked out (ADR-0015): each failed attempt from a source address —
at login, or at the password and code a live session must present before a credential changes —
delays that address's next one, from one second doubling to at most five minutes. An attempt inside
the delay is answered 429 with `Retry-After`. The right credentials always get in once the delay
has passed.

**There are no recovery codes** (ADR-0005). An Admin who has lost their authenticator turns
two-factor off from the host with `pnpm auth:disable-two-factor` — see the
[runbook](docs/runbook.md).

## Testing

Four seams, in descending order of how much lives at each — the reasoning is in the spec.

1. **The HTTP API against a real Postgres** (`pnpm test:api`). The default seam. Ports get fakes;
   the database does not, because the queries and the migrations are part of what is under test.
   The suite creates its own `<database>_test` database on first run.
2. **The tax engine.** Sections 20, 22 and 23, the lots and the form lines, exercised with worked
   examples. In practice these tests also run against Postgres, because the engine replays the
   stored ledger; they live in the same suite.
3. **Ports against recorded fixtures.** Adapters, connectors and the indexer are tested against
   responses recorded under `apps/api/tests/fixtures/`; no test reaches a live venue or provider.
4. **Playwright against the running application** (`pnpm test:e2e`). A few critical journeys only,
   against the dev servers.
   There is deliberately no broad component-test layer.
