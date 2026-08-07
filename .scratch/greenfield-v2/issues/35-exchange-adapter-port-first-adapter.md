# 35 — Exchange adapter port; first adapter

**What to build:** The port that confines a venue's quirks, proven by one real exchange working end to end — credentials in, normalized records out, transactions in the ledger. Core code never learns a venue's name.

**Blocked by:** 34, 31

**Status:** ready-for-agent

- [ ] An adapter translates a venue's API into canonical normalized records — trade, transfer, fill, funding, cash movement, position
- [ ] Adapters never touch the database, never convert to EUR and never compute tax
- [ ] Pagination, rate limits, capped lookback, symbol discovery and request signing are absorbed inside the adapter
- [ ] Adding a venue means one adapter plus a registry entry — no changes to services, routers or the UI
- [ ] Testing and syncing act on the Connection and report results per adapter kind, so one kind failing does not hide another succeeding
- [ ] One real exchange adapter ships and imports history end to end
- [ ] Adapters are tested against recorded fixtures of real venue responses, with no live calls in CI
