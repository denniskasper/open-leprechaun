# 01 — Walking skeleton

**What to build:** From a clean clone and a copied environment file, one documented command brings up the API, the web client and Postgres, and a health endpoint's response is visible in the browser. Nothing else works yet — but the whole path from database to screen is connected and provable.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] `pnpm` scripts at the repository root are the single documented entry point; there is no Makefile
- [ ] Postgres runs in Docker Compose; API and web dev servers run on the host so a debugger can attach
- [ ] A clean clone plus a copied environment file reaches a running app with no undocumented manual step
- [ ] The API serves its OpenAPI documentation
- [ ] The web client fetches the health endpoint and renders its response
- [ ] Backend and frontend dependency versions match those named in the spec
