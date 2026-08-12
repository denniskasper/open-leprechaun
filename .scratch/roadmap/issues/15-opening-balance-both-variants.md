# 15 — Opening Balance, both variants

**What to build:** A position that predates available history can be recorded honestly, and the record distinguishes what is known from what is reconstructed. This matters because an exemption depends on the acquisition date, while the basis may be a genuine estimate.

**Blocked by:** 13

**Status:** done

- [x] An Opening Balance behaves like an inbound transfer but marks its minted lot as estimated
- [x] The two cases are distinct: acquisition date known with basis estimated, and both reconstructed
- [x] Conservative dating is recommended only where the date is genuinely unknown, and the UI explains why
- [x] Where the date is known, the Admin supplies it and it is used as given
- [x] Any later disposal consuming such a lot is flagged as resting on an estimate
- [x] The UI states plainly which figures the choice will affect

## Comments

Implemented. One revision (`c8297dbd809b`) widens the transaction vocabulary with
`opening_balance` and adds its two header declarations; the structural rules live in
`services/transactions.py`, the tax consequence in `services/tax_treatment.py`, and the UI on
`/transactions`.

How each criterion is held:

- **Behaves like an inbound transfer, lot marked estimated**: `opening_balance` requires one
  in-leg and forbids `out` and `fee` (nothing left anywhere, and no fee was paid inside the
  ledger). Its consequence is a new `Inflow.mints_estimated_lot` — pinned by test to never be
  `mints_lot_at_cost`, so the lot engine (19) cannot read it as a documented purchase.
- **The two cases are distinct**: a `reconstructed` column (`basis` | `basis_and_date`) plus
  `estimated_basis_eur`, both CHECKed present exactly when the type is `opening_balance` and
  refused on every other type — the assumption can never look identical to a real movement.
  The service's `declaration_defect` refuses an undeclared or mis-declared event with a
  sentence before anything is written; the estimate is fixed-point end to end (NUMERIC,
  Decimal, string in JSON), may honestly be zero, never negative.
- **Conservative dating recommended only where the date is genuinely unknown**: the form opens
  on the date-known variant; the conservative choice carries copy saying it is deliberately
  late, why (no assumed older exempt acquisition), and that applied to a known date it
  manufactures tax — pinned by unit tests on `RECONSTRUCTED_WORDS`.
- **A known date is used as given**: `occurred_at` is the acquisition instant, and the input's
  label follows the variant — "Acquired at" against "Known history begins at".
- **Disposals flagged**: `tax_treatment.rests_on_estimate` is the predicate the disposal
  engine (21) will read — a rule, not prose, pinned by test across every `Inflow`.
- **The UI states which figures the choice affects**: the date-known copy names the exemption
  (gain excluded entirely after a year) and that the basis only sizes a taxed gain; the ledger
  row wears a caution marker (`basis estimated` / `date & basis reconstructed`) with the
  estimate rendered beside it.

Decisions worth recording:

- **Declarations ride on the transaction header, not the leg**, and an Opening Balance records
  **exactly one position** (`LegRules.single_position`) so the header's declaration is
  unambiguous about what it describes — a second position is its own Opening Balance.
- **The estimate is in EUR**, the numéraire every taxable figure is expressed in.
- **`formatMoneyExact` joins `lib/format.ts`**: money that arrives as a fixed-point decimal
  string, placed in the locale's own currency pattern without the digits ever passing through
  a float; `docs/agents/design.md` § Numbers now names it.
- **Downgrade retypes to `transfer_in`** (the windfall precedent): the earlier schema cannot
  express the declaration, and an unclassified inflow is the honest earlier behaviour — it
  mints no lot, so nothing poses as a documented purchase.
- **The conservative date is supplied, not prefilled**: the app cannot yet know where known
  history starts — coverage windows arrive with ticket 40, which could prefill it later.
- Defect sentences now carry the right article ("An opening balance", "An airdrop").
- The seed carries one date-known Opening Balance (invented fixture values, like every seed
  row); a Playwright spec drives the conservative variant through the browser's own controls
  and sees the marker.
- Post-review fixes (two-axis review): the estimate renders through `formatMoneyExact` rather
  than a hand-appended currency code; the disposal flag became the machine-readable
  `rests_on_estimate` instead of comment prose; `occurredAtWords` falls back to the date-known
  label so the conservative reading is never a default.
- No version bump — releases have not started; like tickets 10–14 this rides as `feat:` until
  one is cut.
