# 19 — Tax Lots as fingerprinted materialisation

**What to build:** Tax Lots are derived from the transaction ledger rather than maintained alongside it, stored only so that holdings and reports need not replay the ledger on every request, and stamped with a fingerprint of the inputs that produced them so a stale lot table is detectable.

**Blocked by:** 13, 14, 15

**Status:** ready-for-agent

- [ ] Every acquisition mints a lot; the ledger is the only source of truth
- [ ] Lots are derived in full from the beginning of time, never incrementally patched
- [ ] Each materialisation records a per-entity fingerprint of its inputs — transactions, corporate actions, instrument classifications, rates used, statutory configuration
- [ ] A lot table whose fingerprint no longer matches the ledger is detectable and identified as such
- [ ] Rebuilding is idempotent: two runs over unchanged inputs produce identical lots
- [ ] An inflow of an unacknowledged Instrument mints no lot
