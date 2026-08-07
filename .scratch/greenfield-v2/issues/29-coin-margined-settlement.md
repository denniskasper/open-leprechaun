# 29 — Coin-margined settlement

**What to build:** An inverse contract settles in the coin rather than a quote currency, so closing one both realises capital income and puts an asset into the ledger. Both consequences are recorded, and neither needs a special rule beyond this ticket.

**Blocked by:** 28, 19

**Status:** ready-for-agent

- [ ] A coin-margined close emits a Section 20 Event for the result, converted at the rate of the close
- [ ] The same close mints a Tax Lot for the settlement asset at its EUR value at close time
- [ ] The minted lot's holding period starts at the close
- [ ] Connectors and adapters that cannot support the variant refuse it explicitly rather than converting it wrongly
- [ ] Tested end to end: a close produces exactly one capital-income event and exactly one lot
