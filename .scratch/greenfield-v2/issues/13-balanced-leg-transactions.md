# 13 — Balanced-leg Transactions

**What to build:** The Admin can record any economic event by hand as a set of legs that balance — what left, what arrived, what a fee consumed — and can edit or delete it afterwards. A trade's other side is structural rather than conventional.

**Blocked by:** 10, 12

**Status:** ready-for-agent

- [ ] A Transaction is a set of legs that balance; a buy records both the asset acquired and the cash spent
- [ ] A fee is its own leg and is never double-counted
- [ ] More than two legs are expressible, so a fee in a third asset is not a special case
- [ ] The transaction vocabulary names what happened for both crypto and securities
- [ ] Each transaction type's tax consequence is documented in one place, which the tax engines alone will read
- [ ] An unclassified inflow is never assumed to be a purchase
- [ ] Manual create, edit and delete work end to end from the UI
- [ ] Monetary and quantity values are fixed-point decimals throughout, including in JSON
