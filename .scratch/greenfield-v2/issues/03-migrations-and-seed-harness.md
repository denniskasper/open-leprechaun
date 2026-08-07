# 03 — Migrations and seed harness

**What to build:** Schema changes ship only as migrations, and a developer can populate a realistic database with one command. Upgrading a deployed instance never means editing the database by hand.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Migrations are linear with no branching heads; one command is the only upgrade path
- [ ] Every migration is tested up and down against a seeded database in CI
- [ ] A migration that cannot be reversed says so explicitly and documents the manual reversal
- [ ] A seed command populates realistic data and refuses to run outside development
- [ ] Running the seed twice leaves the same state as running it once
- [ ] The seed grows with later tickets; at this point it need only prove idempotency
