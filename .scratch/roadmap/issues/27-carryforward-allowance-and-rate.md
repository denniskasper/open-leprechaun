# 27 — Carryforward, allowance and rate

**What to build:** The second half of the §20 engine: unused losses carry forward across years inside their own category, a category can open with a balance established before the ledger existed, the saver's allowance is deducted once across the combined total, and the rate produces the figure that belongs on the return.

After this ticket the engine is complete, and every later producer of capital income need only emit events.

**Blocked by:** 26

**Status:** done

- [x] Each category maintains a running carryforward across years; a year's calculation consumes it before the allowance is applied
- [x] Carryforwards never cross categories
- [x] A year that produced a carryforward states the amount and the category; a year that consumed one states which year it came from
- [x] Each category accepts an opening carryforward entered as per-year configuration from an assessment predating the ledger; absent means zero, not unknown
- [x] Surviving categories are summed after offsetting and carryforward
- [x] The saver's allowance is a deduction, not an all-or-nothing threshold, applied once across the combined total and never per source
- [x] Any portion of the allowance already consumed at source under an exemption order is deducted first, so the app can never claim more allowance than exists
- [x] The rate applies the flat rate and solidarity surcharge, and where church tax is elected, the exact formula including its deduction effect — not an approximation
- [x] The result notes that a personal-rate comparison may apply, without computing it
- [x] All statutory values come from per-year configuration with their sources cited
- [x] Boundary cases are tested explicitly: the allowance exactly consumed, an allowance fully consumed at source, a carryforward exactly exhausted, and a year whose losses exceed everything available
- [x] Every statutory rule has a test naming the paragraph it implements

## Comments

Implemented in `services/section20.py` as the second pair of pure functions beside `net`:

- **`carry`** rolls one year's category balances through their carryforwards. The pot is one
  amount in law (§20 Abs. 6 Satz 3), kept as `CarryforwardLayer`s so a consumption names the year
  it came from — eaten oldest first, a partly eaten layer keeping its origin. A loss year's full
  net loss travels (the cap bounds offsetting, never carrying); in a gain year a configured cap
  bounds consumption too (§20 Abs. 6 Satz 5 second half as configured — dormant since JStG 2024
  struck the caps). Layers never leave their category.
- **`assess`** sums what survives every pot, deducts the Sparerpauschbetrag once across that
  combined total — only what exemption orders have not already consumed at source, never below
  zero (§20 Abs. 9 Satz 4) — and applies the rate: flat × taxable, soli on the tax, and with
  church tax elected the exact §32d Abs. 1 Satz 4 formula `taxable / (1/rate + k)` carrying the
  deduction effect. `TaxDue` states euros because the rate is statutory (ADR-0007's one
  exception); `PERSONAL_RATE_NOTE` names the Günstigerprüfung without computing it.

Decisions worth recording:

- **Opening carryforwards are three optional statutory keys** (`opening_carryforward_<category>`),
  entered per year with the assessment that established them as the source — the one personal
  figure the store holds, so nothing rides in with the migration (`7c50a1d64f2e` re-pins the
  vocabulary CHECK). Absent means zero, never unknown. Riding the store buys the settings screen
  (rows say "not set — none carried"), and the report fingerprint already covers statutory
  configuration, so correcting an opening balance marks dependent reports stale for free.
- **`year_report` is now a chain**: events are gathered for every year up to the target, each
  year netted under its own configured caps and rolled, so the target opens with exactly what its
  predecessors left. A prior year's event awaiting a crypto price blocks the target year (an
  unvalued loss would falsify every carryforward after it); a prior year's stance exclusion is its
  own report's to name and is not re-listed.
- **Allowance consumed at source is wired but fed zero**: the engine takes
  `allowance_used_at_source_eur` and is tested for it (§44a boundary included); the producer
  passes zero until ticket 43's Freistellungsauftrag states what was actually exempted at source —
  the same deferral pattern as ticket 26's withholding fields.
- **Two-axis review folded in**: the migration's downgrade now names the keys it removes
  explicitly, and the two chain behaviours above gained producer tests. The review confirmed the
  church-tax figures against the statute and flagged the used-at-source zero as a deferral to
  record, not a gap to close here.
- No version bump — releases have not started; this rides as `feat:` like tickets 09–26.
