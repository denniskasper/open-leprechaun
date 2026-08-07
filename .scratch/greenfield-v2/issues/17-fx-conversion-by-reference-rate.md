# 17 — FX conversion by reference rate

**What to build:** Every foreign-currency amount converts to EUR by one stated rule, and the conversion is reproducible years later because the rate and its date are stored alongside the result.

**Blocked by:** 11

**Status:** ready-for-agent

- [ ] The euro reference rate for the relevant date is the canonical source, behind a port with a fake
- [ ] Conversion uses the rate of the event date, never of report time
- [ ] The rate and the date it represents are stored with every converted amount
- [ ] Re-running a conversion reproduces the same figure exactly
- [ ] Weekend and holiday dates resolve by one documented rule applied consistently
- [ ] Stablecoin EUR values come from the daily reference rate rather than a crypto price provider
