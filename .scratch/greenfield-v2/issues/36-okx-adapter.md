# 36 — OKX adapter

**What to build:** A second exchange on the port, syncing spot, futures and cash movements forward from an account with no prior history.

**Blocked by:** 35

**Status:** ready-for-agent

- [ ] Spot trades, transfers, futures fills, funding and cash movements are imported as normalized records
- [ ] The adapter proves the port needs no change to accommodate a second venue
- [ ] Sync from an account with no history completes cleanly and reports the period covered
- [ ] Read-only credentials only; the setup screen names the exact scope to grant
- [ ] Tested against recorded fixtures
