# 26 — Section 20 Event and category netting

**What to build:** One event shape that every source of capital income reduces to, and the first half of the engine that consumes it: grouping a year's events by statutory category, netting within each, and applying that category's per-year loss cap. Nothing that produces capital income knows anything about categories, allowances or rates — it emits events, and the engine alone decides.

This is the structural decision the whole project turns on. The shape must be complete and category-driven before any producer is written against it, because a producer written against a futures-shaped calculator cannot later be reused.

The report gains a section showing each category's balance for the year. The allowance, the rate and cross-year carryforward are deliberately **not** in this ticket — they follow in 27.

**Blocked by:** 09, 23

**Status:** ready-for-agent

- [x] A Section 20 Event carries: date, category (`aktien` | `sonstige` | `termingeschaefte`), gross amount, partial-exemption rate, German tax withheld at source split into its components, foreign withholding with source country, and a reference to the producing record
- [x] The three categories are tracked separately at every stage; a loss in one never offsets a gain in another
- [x] Losses from share sales offset only gains from share sales
- [x] Losses in the other-income category offset other income in that category, including dividends
- [x] The per-category annual loss cap is read per year from configuration, never from a constant in logic, and a category with no cap configured is uncapped
- [x] The engine, at this stage: groups a year's events by category, nets within each category, and applies each category's cap — producing a per-category result
- [x] Each category's balance for the year is shown in the report so its form line can be filled directly
- [x] The partial-exemption rate is applied to an event before it enters its category
- [x] Every output figure is traceable to the events that produced it
- [x] The engine is a pure function of events and configuration with no database dependency
- [x] Every statutory rule has a test naming the paragraph it implements, with a fixture that would fail if the rule were dropped
- [x] Boundary cases are tested explicitly: a loss exactly at a category's cap, a category netting to exactly zero, and an event on each side of a tax-year boundary

## Comments

Implemented in `services/section20.py`: the frozen `Section20Event` (Berlin-local date, category,
gross, Teilfreistellung rate, `GermanWithholding` split KESt/Soli/church tax, `ForeignWithholding`
with country, `source` naming the producing record, e.g. `leg:42`) and the pure first half of the
engine — `net(events, year=…, caps=…)`: group by Verlustverrechnungstopf, apply the exemption per
event (`CategoryEntry` keeps event and counted amount side by side for traceability), net within
each pot, bound a negative pot by its cap. Every `CategoryBalance` states `net_eur`, `cap_eur`
(None = uncapped), `balance_eur` for the form line, and `loss_beyond_cap_eur` — the amount the cap
held back, which is exactly what ticket 27's carryforward picks up. An event claiming a fourth
category is refused loudly, never dropped. Reports gain a `section20` figures key (the one-line
mechanism ticket 23 built), and `_frozen` learned plain `date` for it.

Decisions worth recording:

- **The producer shipped here too**: `year_report` reduces the ledger's §20-typed income —
  `dividend`, `distribution`, `interest`, which `tax_treatment` had already routed to this ticket —
  to events, all into the sonstige pot: the aktien pot holds share *sales* alone
  (§20 Abs. 6 Satz 4 EStG), so securities disposals (46) and futures (28) will emit into theirs.
  The emitters know what they are, never how the pots treat them (ADR-0013).
- **Withholding fields exist, nothing populates them**: tickets 43/47 state what was actually
  taken at source. Teilfreistellung stays zero in the producer because no fund Instrument exists
  yet (44); the `year_report` docstring records that once one does, an unclassified fund must
  block finalisation rather than silently assume a zero rate.
- **Caps**: read via a new `statutory.optional_value` (sharing a `_stored_value` scan with
  `required_value`), keyed by `section20.LOSS_CAP_KEYS`. Absent means uncapped, never unknown —
  JStG 2024 struck the §20 Abs. 6 Satz 5/6 caps, so no year seeds one and no blocker wants one.
- **While any event awaits a crypto price the year states no balances** and names the legs —
  netting around a missing member could flip a pot's sign, so no pot pretends. Stance exclusion
  mirrors §22: what a stance keeps out is named beside the balances, never hidden.
- **Two-axis review folded in**: the stance-exclusion rule the §22 engine had privately is now
  `stances.income_excluding_stance`, shared by both income engines before ticket 28 makes a third
  copy; the statutory scan deduplicated; naming and a test-unpacking nit fixed. Deliberately kept:
  `net` filters by year itself (the boundary rule is the engine's own contract, tested at the pure
  seam), and the per-engine `ExcludedEvent` dataclasses stay separate — each is a frozen report
  shape, not shared vocabulary.
- No version bump — releases have not started; like tickets 09–25 this rides as `feat:` until one
  is cut.
