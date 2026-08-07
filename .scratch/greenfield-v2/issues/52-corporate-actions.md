# 52 — Corporate actions

**What to build:** Issuer events that change a holding without a trade are recorded properly, so share counts and cost basis stay right without hand-editing lots. Where the treatment is fact-specific, the app records the event and refuses to assert one.

**Blocked by:** 19

**Status:** ready-for-agent

- [ ] A split or reverse split rescales the quantity of every open lot by the ratio and rescales per-unit basis inversely; total basis and acquisition dates are unchanged and no taxable event arises
- [ ] A capital return reduces the cost basis of open lots rather than booking income, and is reported as such
- [ ] A spin-off or merger is recorded, splits the basis by a ratio the Admin supplies, and is flagged for manual review
- [ ] Every corporate action shows a before-and-after preview of the affected lots before it is applied
- [ ] Every corporate action is reversible
- [ ] Because lots are derived, reversal is the removal of the event followed by a rebuild
- [ ] An Instrument's identifier history absorbs an identifier change so no lot is orphaned
