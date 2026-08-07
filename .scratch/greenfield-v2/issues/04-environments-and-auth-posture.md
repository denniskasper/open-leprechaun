# 04 — Environments and auth posture

**What to build:** One environment variable switches the application between development, integration and production, and the difference is visible on screen. Development skips authentication entirely so there is no login friction; the other two require it.

**Blocked by:** 01, 02

**Status:** ready-for-agent

- [ ] A single variable selects the environment; nothing else differs between them
- [ ] Development skips authentication entirely — no setup, no login
- [ ] Integration and production require authentication
- [ ] The UI shows an environment badge outside production and none within it
- [ ] The version line shows a short commit hash in development and a release version elsewhere
