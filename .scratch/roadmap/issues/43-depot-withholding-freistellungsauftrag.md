# 43 — Depot, withholding and exemption order

**What to build:** A brokerage account can be registered as a **Depot** with the tax semantics its broker actually has — whether tax is withheld at source, and how much of the saver's allowance has already been consumed there.

**Blocked by:** 10

**Status:** ready-for-agent

- [ ] A Depot is an Account under a broker Platform — vocabulary in the UI, not a table or a subtype
- [ ] Withholding behaviour lives on the Platform, with a nullable per-Account override for a brand operating through several entities
- [ ] A Depot records label, reference and base currency
- [ ] Withholding behaviour must be set before a Depot can hold a position
- [ ] A nullable exemption-order amount lives on the withholding Platform; absent means none
- [ ] A Depot may hold cash balances in one or more currencies
