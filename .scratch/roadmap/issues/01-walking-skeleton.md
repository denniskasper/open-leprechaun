# 01 — Walking skeleton

**What to build:** From a clean clone and a copied environment file, one documented command brings up the API, the web client and Postgres, and a health endpoint's response is visible in the browser. Nothing else works yet — but the whole path from database to screen is connected and provable.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] `pnpm` scripts at the repository root are the single documented entry point; there is no Makefile
- [x] Postgres runs in Docker Compose; API and web dev servers run on the host so a debugger can attach
- [x] A clean clone plus a copied environment file reaches a running app with no undocumented manual step
- [x] The API serves its OpenAPI documentation
- [x] The web client fetches the health endpoint and renders its response
- [x] Backend and frontend dependency versions match those named in the spec

## Comments

Implemented. The path is proven at two seams: `pnpm test:api` asserts the health endpoint against a
real Postgres, and `pnpm test:e2e` drives a browser against the running stack and reads the result
off the screen.

Deviations worth recording:

- **Default Postgres host port is 5434, not 5432.** A Postgres already on the host would otherwise
  collide. Configurable in `.env`.
- **Alembic is not installed yet.** The spec names it in the backend stack, but nothing here runs a
  migration; it arrives with ticket 03 rather than sitting unused.
- **shadcn/ui is not installed yet.** Ticket 02 owns the design foundation. Note that this ticket
  does not leave that slate blank: `apps/web/src/index.css` carries a full Tailwind token layer plus
  the aesthetic built on it (an instrument-panel treatment — grid, grain, signal lamp, staggered
  reveal). `AGENTS.md` requires the `/frontend-design` skill for any UI, so the health screen could
  not be styleless. Ticket 02 should treat this as a starting point to extend **or replace**, not as
  a neutral base.
- **Fonts are self-hosted** via `@fontsource-variable` rather than loaded from a CDN. Embedding
  Google Fonts in self-hosted software that holds one person's financial history is the wrong
  default, and in Germany specifically a contested one.
- **The health endpoint answers 503 when the database is unreachable**, with a body that still says
  what is wrong, so the client renders a degraded state rather than an error.
- **The git hooks named in `AGENTS.md` remain untracked, by necessity.** They match on the specific
  figures that have leaked before, so committing them would be the leak they prevent. The README now
  states that recreating them is a deliberate manual step after a clean clone.
- **`repositories/` does not exist yet.** The only query in this ticket is a `SELECT 1` connectivity
  probe, which lives with the engine in `db.py`. The third layer arrives with the first query that
  has a domain subject.
