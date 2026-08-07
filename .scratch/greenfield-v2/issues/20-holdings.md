# 20 — Holdings

**What to build:** One view of everything held — crypto and cash — with quantity, average cost, current value, unrealised result and where it sits. Cost basis comes from Tax Lots, so the portfolio and the tax report cannot disagree.

**Blocked by:** 19, 17, 18

**Status:** ready-for-agent

- [ ] Every position shows Instrument, family, quantity, average cost, current value, unrealised result and location
- [ ] Cost basis is read from Tax Lots, never summed from inflows
- [ ] Grouping by asset class, by Platform and by custody type
- [ ] Cash appears as its own line
- [ ] Unpriced, ignored and dangerous positions carry an explicit marker and are excluded from totals
- [ ] Values render in a selected display currency; the choice never affects a tax figure
- [ ] Extra software required to reach an Account is shown on its holdings
- [ ] The view responds within a second at the target scale
