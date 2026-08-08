# 55 — Health panel

**What to build:** One page that answers whether the numbers on every other page are fresh — and when something is wrong, names it precisely instead of blaming everything.

**Blocked by:** 35, 42

**Status:** ready-for-agent

- [ ] Per data provider: last successful call, last error, and rate-limit state
- [ ] Per Connection: last sync, per-kind result and last failure message
- [ ] Per scheduled task: last run and next due time
- [ ] Database size and stored price-history row counts
- [ ] A single failing provider is named along with the Instruments it affects — never reported as a total outage
- [ ] Every problem shown links to the screen that resolves it
