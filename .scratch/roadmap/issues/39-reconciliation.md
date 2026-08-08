# 39 — Reconciliation

**What to build:** The app compares what a venue says is held against what the transactions account for, and surfaces the difference rather than absorbing it. A gap is reported and never filled in by guesswork.

**Blocked by:** 35, 19

**Status:** ready-for-agent

- [ ] Reconciliation runs per Connection and reports live balance, tracked balance and the difference per Instrument
- [ ] The tolerance is configurable
- [ ] A gap is reported and never auto-filled; no cost basis is invented
- [ ] Each gap offers the two honest resolutions — import the missing history, or record an Opening Balance with its uncertainty marked
- [ ] Synced positions are used for reconciliation only, never as a substitute for transactions
- [ ] Works for crypto balances and for cash
- [ ] A non-authoritative second source may reconcile against an Account without writing to it
