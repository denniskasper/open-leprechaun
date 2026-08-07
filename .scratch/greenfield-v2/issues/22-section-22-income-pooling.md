# 22 — §22 income pooling

**What to build:** Staking rewards, lending interest, mining and qualifying airdrops are valued at receipt, mint a lot at that basis, and pool under their own annual limit.

**Blocked by:** 21

**Status:** ready-for-agent

- [ ] Income is valued at market value on receipt and simultaneously mints a lot at that basis
- [ ] All qualifying income pools under a single annual limit read from configuration
- [ ] The limit applies as "less than", so exactly the threshold is already fully taxable
- [ ] The result states a taxable amount and never a euro tax owed, because the marginal rate is unknown
- [ ] Classification follows the transaction type, and the result names which events it pooled
- [ ] Delegation is tracked as an informational marker per Account and Instrument, carries no tax meaning, and does not affect any holding period
- [ ] Delegation events found during import are surfaced as warnings, never imported as transactions
