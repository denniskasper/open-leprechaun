# 04 — Environments and auth posture

**What to build:** One environment variable switches the application between development and production, and the difference is visible on screen. Development skips authentication entirely so there is no login friction; production requires it.

**Blocked by:** 01, 02

**Status:** done

- [x] A single variable selects the environment; nothing else differs between them
- [x] Development skips authentication entirely — no setup, no login
- [x] Production requires authentication

## Comments

Narrowed from three environments to two (2026-08-08, Admin's call): development happens only on
the laptop and exactly one deployed instance exists, so there is no integration environment.
Ticket 03 already ships the `ENVIRONMENT` setting with exactly these two values.
- [x] The UI shows an environment badge outside production and none within it
- [x] The version line shows a short commit hash in development and a release version elsewhere

Implemented (2026-08-08): `GET /api/meta` reports environment and version — the
commit hash of the working copy in development, `RELEASE_VERSION` (defaulting to
the package version) elsewhere. `open_leprechaun.auth.require_admin` is the
dependency every future non-public route takes: development returns the admin
without credentials, production answers 401 until the login ticket (07) supplies
something to verify. The shell shows a `dev` badge in the header outside
production and a version line at the foot of the sidebar and the mobile sheet.
