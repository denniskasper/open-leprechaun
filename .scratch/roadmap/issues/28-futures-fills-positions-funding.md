# 28 — Futures fills, positions and funding

**What to build:** Imported futures activity is stored as immutable fills, positions are reconstructed from them, funding is attributed to the position it belongs to, and the whole thing emits Section 20 Events — it computes no tax of its own.

**Blocked by:** 27

**Status:** ready-for-agent

- [ ] Fills are stored as received and deduped on source and external identifier
- [ ] Positions are derived from the ordered fill sequence per symbol and rebuilt idempotently per source
- [ ] Derivation uses position side, reduce-only and per-fill realised result where the venue exposes them, and documented net accounting otherwise
- [ ] Manually entered and derived positions share one model and one tax treatment; only origin differs
- [ ] Funding is attributed to the position open for that symbol at the payment timestamp
- [ ] Funding, trading fees and realised result are stored separately and summed into a net figure
- [ ] Unattributable funding is surfaced, never dropped
- [ ] A closed position emits a Section 20 Event in the `termingeschaefte` category and computes no tax itself
- [ ] A position counts in the year it closed; an open position counts in no year
