# 22 — §22 income pooling

**What to build:** Staking rewards, lending interest, mining and qualifying airdrops are valued at receipt, mint a lot at that basis, and pool under their own annual limit.

**Blocked by:** 21

**Status:** ready-for-agent

- [x] Income is valued at market value on receipt and simultaneously mints a lot at that basis
- [x] All qualifying income pools under a single annual limit read from configuration
- [x] The limit applies as "less than", so exactly the threshold is already fully taxable
- [x] The result states a taxable amount and never a euro tax owed, because the marginal rate is unknown
- [x] Classification follows the transaction type, and the result names which events it pooled
- [x] Delegation is tracked as an informational marker per Account and Instrument, carries no tax meaning, and does not affect any holding period
- [x] Delegation events found during import are surfaced as warnings, never imported as transactions

## Comments

Implemented. One migration — the `staking_delegation` marker table; the engine itself derives
and persists nothing, mirroring ticket 21: the code lives in `services/section22.py`, its one
public read `year_report(engine, source, year=…)`, driven in tests over real Postgres with rates
through the reference-rate port's fake.

How each criterion is held:

- **Valued at market value on receipt, minting a lot at that basis**: the valuation rule is one
  shared function — `fx.value_eur`, extracted from ticket 21's `_value_eur` (ADR-0017: the
  numéraire by quantity, foreign cash by its own daily rate, a stablecoin by its peg's) — applied
  to the same in-leg at the same instant on both sides. The lot engine already mints the leg's
  lot with `basis_source = market_value` (now the exported `lots.MARKET_VALUE`); its *stored*
  basis stays None until the rate tickets extend the derivation, so the disposal engine (21) now
  states such a basis at report time by the same rule at the acquisition instant. Income and
  cost basis therefore agree to the cent, pinned by a test that stakes, sells, and compares the
  §22 income with the §23 consumption's basis. A value needing a crypto price (ticket 18) makes
  the event **awaiting valuation**: named in the report, and while any pooled event awaits one
  the year states no total and no verdict. Only the requested year is valued. Post-review fix:
  only a *counting* slice's basis is valued — a Haltefrist-exempt consumption is excluded from
  the total, so it costs no rate lookup at its old acquisition date and a rate gap there cannot
  crash the year (pinned by test; ticket 21's "an exempt disposal blocks nothing" holds).
- **One annual limit from configuration**: `other_income_exemption_limit`, read per year through
  the extracted `statutory.required_value` (also now used by ticket 21's engine); an unset year
  refuses by name (`statutory.StatutoryValueUnsetError`, re-exported where the engines raise
  it). A custom per-year value (300 €) proves no constant hides in logic.
- **"Less than"** (§22 Nr. 3 Satz 2 EStG, *weniger als*): tested one cent below (free, headroom
  stated), exactly at (fully taxable, overshoot zero) and one cent above the threshold.
- **A taxable amount, never a euro owed** (ADR-0007): the `FreigrenzeVerdict` vocabulary is
  amounts only — a test pins the dataclass fields against rates and "owed".
- **Classification follows the transaction type**: the four §22 types are selected by the
  `income` field of `tax_treatment.TAX_CONSEQUENCES` (now the shared `SECTION_22`/`SECTION_20`
  constants rather than duplicated strings), and each pooled `IncomeEvent` wears its type, leg,
  Account, Instrument, instant, quantity and value. A trade, a kept windfall (no Leistung, BMF
  letter of 10.05.2022) and §20 interest pool nothing — pinned by test. The Tax Year buckets by
  Berlin local date (both sides of the year boundary tested).
- **Delegation marker**: `staking_delegation` per (Instrument, Account) with an optional note,
  upserted because the marker describes the present; removing it means "no longer delegated".
  It is deliberately not a fingerprint input class — tests pin that marking drifts no
  materialisation and that a delegated holding's disposal stays Haltefrist-exempt.
- **Delegation on import**: the transaction vocabulary has no delegation type (pinned:
  delegate/undelegate/stake/unstake are not types), so a delegation cannot even be recorded as a
  transaction; `delegation.import_warning` composes the sentence the import framework
  (ticket 31) surfaces, telling the Admin to record any real movement as a self-transfer. This
  half stays forward-provisioned until ticket 31 wires it.

Decisions worth recording:

- **An event pools exactly when its in-leg mints** (services/stances): unacknowledged is deny by
  default (ADR-0012) and ignored/dangerous never enters — but the report **names what stance
  kept out** (`excluded`, wearing the stance), so a tax-free verdict can never silently hide a
  reward waiting in the inbox. Numéraire income has no lot to mint and pools unconditionally at
  its own quantity.
- **Fees and Werbungskosten are out of scope**: the engine states income gross at market value;
  the criteria ask for no deduction machinery.
- **The verdict shape is §22's own** — deliberately not shared with §23's `FreigrenzeVerdict`:
  the arithmetic coincides but the vocabulary (`total_income_eur` vs `total_gain_eur`, and §23's
  netting of losses) is per-regime and load-bearing.
- Two-axis review fixes folded in: the "importer" Avoid-line breach in prose (now "an import"),
  `repositories/delegations.mark` inspecting the constraint name instead of swallowing any
  IntegrityError, and the named `excluded` events above. Deliberately not taken: extracting the
  duplicated Freigrenze arithmetic (per-regime vocabulary wins), deduplicating the per-file test
  helpers (the repo's self-contained test-file convention), and renaming `fx.ValuableInstrument`.
- **No endpoint and no UI**: like ticket 21, the report lifecycle and any surface belong to
  tickets 23–25; the delegation marker's surface arrives with holdings/health screens. The seed
  gains an idempotent `_delegations` step (the seed's own contract: each ticket that adds a
  table appends one).
- No version bump — releases have not started; like tickets 09–21 this rides as `feat:` until
  one is cut.
