# 27 — Carryforward, allowance and rate

**What to build:** The second half of the §20 engine: unused losses carry forward across years inside their own category, a category can open with a balance established before the ledger existed, the saver's allowance is deducted once across the combined total, and the rate produces the figure that belongs on the return.

After this ticket the engine is complete, and every later producer of capital income need only emit events.

**Blocked by:** 26

**Status:** ready-for-agent

- [ ] Each category maintains a running carryforward across years; a year's calculation consumes it before the allowance is applied
- [ ] Carryforwards never cross categories
- [ ] A year that produced a carryforward states the amount and the category; a year that consumed one states which year it came from
- [ ] Each category accepts an opening carryforward entered as per-year configuration from an assessment predating the ledger; absent means zero, not unknown
- [ ] Surviving categories are summed after offsetting and carryforward
- [ ] The saver's allowance is a deduction, not an all-or-nothing threshold, applied once across the combined total and never per source
- [ ] Any portion of the allowance already consumed at source under an exemption order is deducted first, so the app can never claim more allowance than exists
- [ ] The rate applies the flat rate and solidarity surcharge, and where church tax is elected, the exact formula including its deduction effect — not an approximation
- [ ] The result notes that a personal-rate comparison may apply, without computing it
- [ ] All statutory values come from per-year configuration with their sources cited
- [ ] Boundary cases are tested explicitly: the allowance exactly consumed, an allowance fully consumed at source, a carryforward exactly exhausted, and a year whose losses exceed everything available
- [ ] Every statutory rule has a test naming the paragraph it implements
