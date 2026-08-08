# 04 — Environments and auth posture

**What to build:** One environment variable switches the application between development and production, and the difference is visible on screen. Development skips authentication entirely so there is no login friction; production requires it.

**Blocked by:** 01, 02

**Status:** ready-for-agent

- [ ] A single variable selects the environment; nothing else differs between them
- [ ] Development skips authentication entirely — no setup, no login
- [ ] Production requires authentication

## Comments

Narrowed from three environments to two (2026-08-08, Admin's call): development happens only on
the laptop and exactly one deployed instance exists, so there is no integration environment.
Ticket 03 already ships the `ENVIRONMENT` setting with exactly these two values.
- [ ] The UI shows an environment badge outside production and none within it
- [ ] The version line shows a short commit hash in development and a release version elsewhere
