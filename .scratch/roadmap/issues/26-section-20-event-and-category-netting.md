# 26 — Section 20 Event and category netting

**What to build:** One event shape that every source of capital income reduces to, and the first half of the engine that consumes it: grouping a year's events by statutory category, netting within each, and applying that category's per-year loss cap. Nothing that produces capital income knows anything about categories, allowances or rates — it emits events, and the engine alone decides.

This is the structural decision the whole rebuild turns on. The shape must be complete and category-driven before any producer is written against it, because a producer written against a futures-shaped calculator cannot later be reused.

The report gains a section showing each category's balance for the year. The allowance, the rate and cross-year carryforward are deliberately **not** in this ticket — they follow in 27.

**Blocked by:** 09, 23

**Status:** ready-for-agent

- [ ] A Section 20 Event carries: date, category (`aktien` | `sonstige` | `termingeschaefte`), gross amount, partial-exemption rate, German tax withheld at source split into its components, foreign withholding with source country, and a reference to the producing record
- [ ] The three categories are tracked separately at every stage; a loss in one never offsets a gain in another
- [ ] Losses from share sales offset only gains from share sales
- [ ] Losses in the other-income category offset other income in that category, including dividends
- [ ] The per-category annual loss cap is read per year from configuration, never from a constant in logic, and a category with no cap configured is uncapped
- [ ] The engine, at this stage: groups a year's events by category, nets within each category, and applies each category's cap — producing a per-category result
- [ ] Each category's balance for the year is shown in the report so its form line can be filled directly
- [ ] The partial-exemption rate is applied to an event before it enters its category
- [ ] Every output figure is traceable to the events that produced it
- [ ] The engine is a pure function of events and configuration with no database dependency
- [ ] Every statutory rule has a test naming the paragraph it implements, with a fixture that would fail if the rule were dropped
- [ ] Boundary cases are tested explicitly: a loss exactly at a category's cap, a category netting to exactly zero, and an event on each side of a tax-year boundary
