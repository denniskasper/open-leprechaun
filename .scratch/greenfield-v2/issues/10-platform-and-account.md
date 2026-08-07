# 10 — Platform and Account

**What to build:** The Admin can register the places that hold value and the holdings under them. A **Platform** is any such place, distinguished by kind; an **Account** is one holding under exactly one Platform, and it is the boundary for FIFO lot matching.

**Blocked by:** 03, 07, 02

**Status:** ready-for-agent

- [ ] Platform kinds cover exchange, cold storage, software wallet, broker and bank
- [ ] Every Account belongs to exactly one Platform; none is locationless
- [ ] Settings groups Platforms by kind
- [ ] An Account records an address, reference or identifier as metadata only, never as a data source
- [ ] An Account records extra software required to reach it, surfaced later on the holding
- [ ] An Account can be scoped as finely as its Platform evidences — the model permits several Accounts per Platform and per chain
- [ ] The vocabulary in code, API and UI is Platform and Account; "Exchange" appears only for the exchange kind
