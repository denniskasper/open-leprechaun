# 18 — Crypto prices with fallback chain

**What to build:** Every crypto Instrument gets a price from some provider in a documented chain, and when they all fail the Admin sees the last known price clearly labelled stale rather than a blank or a zero.

**Blocked by:** 11

**Status:** ready-for-agent

- [ ] A price provider port with at least two implementations and a fake, tried in documented order
- [ ] No provider-specific identifier being absent may exclude an Instrument from pricing
- [ ] The last known price is stored with its source and timestamp
- [ ] When every provider fails, the stored price is served and clearly labelled stale
- [ ] Staleness is reported by naming the affected Instruments, never as a blanket outage
- [ ] A rate-limit response is surfaced as its own named condition, distinct from an outage
- [ ] Daily closes are stored per Instrument with source attribution, and a backfill can populate a chosen range
