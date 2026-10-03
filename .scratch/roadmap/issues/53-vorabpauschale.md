# 53 — Advance lump sum for accumulating funds

**What to build:** The annual advance lump sum on an accumulating fund, computed per fund per year, declared in the right year, and deducted from the eventual sale so the same amount is never taxed twice.

This ships unexercised: nothing can accrue one until a fund has been held across a year boundary, so its correctness rests entirely on hand-computed fixtures. Build it accordingly.

**Blocked by:** 46, 09

**Status:** done

- [x] The base yield is the start-of-year value times the annual base rate times the statutory factor
- [x] The amount is the base yield less that year's distributions, floored at zero, then capped at the year's increase in redemption value — in that order
- [x] The base yield is reduced by one twelfth for each full month preceding the month of acquisition — built as the statute and the form have it: the *amount after the cap* is reduced (see Comments)
- [x] A fund whose value fell over the year produces zero
- [x] No amount is computed for a fund not held at the accrual moment — a fund sold during the year produces none
- [x] The model distinguishes the year the amount derives from and the year it is declared in; accrual is the first banking day of the following year
- [x] The amount is reduced by the fund's partial exemption and emits a Section 20 Event in the other-income category
- [x] Accumulated amounts are tracked per lot and deducted from the gain on eventual sale; a partially consumed lot keeps its accumulation proportionally
- [x] The annual base rate and the fund's start- and end-of-year redemption values are entered as per-year configuration with their source shown
- [x] The app refuses to compute a year with any required value unset, and registers that as a finalisation blocker, rather than substituting a market close
- [x] Every rule has a fixture that would fail if the rule were dropped

## Comments

Implemented as a producer beside the engine: `services/advance_lump_sums.py` holds the pure
per-unit rule, its calendar, and the read that says which lots were held at each accrual;
`section20.year_report` reduces each record to one Section 20 Event (ADR-0013), and
`services/security_disposals` deducts what a consumed lot accrued.

How each criterion is held:

- **Base yield, order of operations, zero on a fall**: `per_unit` — start value x Basiszins x
  factor; less distributions, floored at zero, then capped at the rise, never below zero. One
  fixture per rule, each with a figure that changes if the rule is dropped; the order fixture
  states what the reversed order would give.
- **Twelfths**: `twelfths_held`, applied per Tax Lot — each lot wears its own acquisition month.
- **Held at the accrual moment**: the single ledger replay says where every unit ended (still in
  a queue, or finally consumed on a date); a unit accrues for a year when it was acquired by the
  end of it and not finally consumed before the accrual date. A lot a confirmed self-transfer
  carried counts where it came to rest, with its original acquisition month.
- **Two years, one accrual date**: every record names `derived_year`, `declared_year` and
  `accrued_on` — 2 January of the following year, or the Monday after where that is a weekend.
  The event is dated there, which is what puts it in the later return.
- **Teilfreistellung and pot**: the event wears the fund's rate for the declared year and enters
  `sonstige`; the engine exempts. Anlage KAP-INV gained the Vorabpauschalen block (Zeilen 9-13,
  before Teilfreistellung).
- **Per lot, deducted at sale, proportional**: accrual and deduction are one function
  (`Schedule.lot_amount`: quantity x per-unit amount x twelfths / 12) read from two sides, so a
  partially consumed lot keeps its share by construction and nothing is stored that could drift
  from the ledger (ADR-0014). `SecurityConsumption` and `SecurityDisposal` state the deducted
  amount; `gain_eur` is after it, before Teilfreistellung — the form's Zeile 53.
- **Entered configuration with sources**: the Basiszins was already a statutory key; the factor
  joined it (`advance_lump_sum_factor`, required, seeded 0.7 for 2024-2026 by migration
  `d8a2c5f61b90`). The fund's figures live in the new `fund_redemption_value` table, entered
  through `/api/fund-redemption-values` and the statutory settings screen, source required.
- **Refusal and blocker**: an unset Basiszins or factor raises `StatutoryValueUnsetError`, an
  unset fund year `FundValueUnsetError` (HTTP 409 on generation); the pre-flight registers
  `missing_advance_lump_sum_inputs`, naming every gap. No code path reads a security price.
- **Fixtures**: `tests/test_advance_lump_sums.py`, every expected figure hand-computed.

Decisions worth recording:

- **The twelfths reduce the amount after the cap, not the base yield before it.** This ticket and
  the glossary said "the base yield is reduced"; §18 Abs. 2 InvStG reduces the *Vorabpauschale*,
  and the Anlage KAP-INV reduces its Zeile 41 (after cap and distributions) in Zeile 42
  (`docs/research/tax-form-lines.md`). The two readings differ whenever the cap binds or the
  fund distributed. Built to the statute and the form; a fixture pins the difference and
  CONTEXT.md now says so. Worth a second pair of eyes before the first live run.
- **Distributions per unit are entered with the redemption prices**, not derived from the
  ledger's receipts: they are the fund's published figure (the form's Zeile 37), and a receipt
  only states them for units held on the day it was paid. Zero is a statement, never a default.
- **Every fund accrues, not only accumulating ones** — §18 applies wherever distributions fall
  short of the base yield. A distributing fund held across a year end therefore needs its
  values entered too.
- **Values are entered in EUR per unit.** A fund priced in another currency is converted by
  whoever enters it, with the source saying how.
- **Amounts stay exact**; cents appear at the engine's Teilfreistellung split and at
  presentation (services/rounding), so accrual and later deduction can never differ by a cent.
- **A zero amount is a record with no event** — the working stays visible in the report's
  `advance_lump_sums`, nothing is transcribed.
- **A carried lot's accrual is stated in the Depot where the lot came to rest**, not
  necessarily the one holding it on the accrual date; the amount is the same, but the Depot
  decides the withheld / to-declare side on the forms. Left as is — the two differ only for a
  lot moved between a withholding and a non-withholding Depot after an accrual.
- **In a Depot that withholds at source** the amount is still an event, on the withheld side of
  the forms, with no withholding components stated — the same treatment ticket 46 gives a
  disposal there.
- **The fingerprint gained `fund_redemption_values`**, so every stored report reads stale once;
  the frozen shape changed anyway (new section 20 fields), so they must be regenerated.
- No version bump — releases have not started.
