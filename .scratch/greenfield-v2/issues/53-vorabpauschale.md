# 53 — Advance lump sum for accumulating funds

**What to build:** The annual advance lump sum on an accumulating fund, computed per fund per year, declared in the right year, and deducted from the eventual sale so the same amount is never taxed twice.

This ships unexercised: nothing can accrue one until a fund has been held across a year boundary, so its correctness rests entirely on hand-computed fixtures. Build it accordingly.

**Blocked by:** 46, 09

**Status:** ready-for-agent

- [ ] The base yield is the start-of-year value times the annual base rate times the statutory factor
- [ ] The amount is the base yield less that year's distributions, floored at zero, then capped at the year's increase in redemption value — in that order
- [ ] The base yield is reduced by one twelfth for each full month preceding the month of acquisition
- [ ] A fund whose value fell over the year produces zero
- [ ] No amount is computed for a fund not held at the accrual moment — a fund sold during the year produces none
- [ ] The model distinguishes the year the amount derives from and the year it is declared in; accrual is the first banking day of the following year
- [ ] The amount is reduced by the fund's partial exemption and emits a Section 20 Event in the other-income category
- [ ] Accumulated amounts are tracked per lot and deducted from the gain on eventual sale; a partially consumed lot keeps its accumulation proportionally
- [ ] The annual base rate and the fund's start- and end-of-year redemption values are entered as per-year configuration with their source shown
- [ ] The app refuses to compute a year with any required value unset, and registers that as a finalisation blocker, rather than substituting a market close
- [ ] Every rule has a fixture that would fail if the rule were dropped
