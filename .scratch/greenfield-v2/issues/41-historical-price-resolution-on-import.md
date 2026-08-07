# 41 — Historical price resolution on import

**What to build:** An imported row without a price gets the price that applied at its timestamp, so cost basis and income valuations are real rather than backfilled from today's price.

**Blocked by:** 31, 18

**Status:** ready-for-agent

- [ ] Resolution uses the price at the transaction's timestamp; daily granularity is acceptable, finer preferred where available
- [ ] A row whose price cannot be resolved is flagged rather than defaulted to zero
- [ ] Unresolvable rows are listed in the import result
- [ ] The resolved price records its provider and the timestamp it represents
- [ ] An Instrument valued at zero because nothing prices it is treated as unknown, never as immaterial
