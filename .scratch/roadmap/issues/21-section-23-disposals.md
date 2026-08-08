# 21 — §23 disposals

**What to build:** Crypto disposals are matched against acquisitions FIFO within the Account that held them, holding periods decide exemption, and the annual all-or-nothing limit is applied from configuration rather than from constants in logic.

**Blocked by:** 19, 09

**Status:** ready-for-agent

- [x] Disposals consume lots FIFO within the same Account and Instrument
- [x] Each consumption records quantity, basis, proceeds, holding period in days and a long-term flag
- [x] A disposal exceeding available lots is a hard error naming the shortfall, never a silent zero-basis fill
- [x] Disposals held beyond the statutory period are exempt, excluded from the total, and still visible in detail
- [x] The holding period is computed between absolute instants and is unaffected by timezone
- [x] A self-transfer does not restart the holding period
- [x] The exemption limit is read per year from configuration; below it the whole amount is free, at or above it the full amount is taxable
- [x] Headroom or overshoot against the limit is stated explicitly
- [x] The tax year is bucketed by German local date while timestamps remain absolute instants
- [x] Tests name the paragraph each rule implements; boundary cases are tested at, just below and just above every threshold, and on both sides of a year boundary in winter and summer time

## Comments

Implemented. No migration — the engine derives and persists nothing; the code lives in
`services/section23.py`, its one public read `year_report(engine, source, year=…)`, driven in
tests over real Postgres with rates through the reference-rate port's fake.

How each criterion is held:

- **FIFO within Account and Instrument**: the engine does not replay FIFO itself — the lot
  engine's `derive` (ticket 19) now returns a `Derivation`: the lots it mints *and* what each
  consuming leg took from its queue, recorded in the same chronological pass. A disposal and
  the lots it consumed can therefore never disagree, and the per-Account boundary is pinned by
  a test where a same-Instrument lot at another Account cannot fill a disposal.
- **Each consumption records** quantity, acquisition instant, basis (with its `basis_source`),
  its pro-rata share of proceeds (cent-exact, remainder on the last share), holding days and
  the long-term flag; the disposal above it carries proceeds, costs and the Tax Year.
- **Shortfall is a hard error**: `LotShortfallError` names the missing quantity and instant.
  It fires for a gap in *any* year, not just the requested one — every later consumption's
  FIFO position rests on it. A stance that never enters the cost basis (ignored/dangerous) is
  the one exception: such an outflow stays a ledger entry, never quietly a sale and never an
  error over lots that were deliberately not minted; the rule is the extracted
  `stances.never_enters_cost_basis`, shared with the lot engine's transfer-destination check.
- **Haltefrist** (§23 Abs. 1 Satz 1 Nr. 2 EStG): exempt strictly beyond one year, excluded
  from the Gesamtgewinn, stated in full in the detail. The threshold is judged to the second
  between absolute instants — one year after an instant is the same UTC timestamp one year on,
  a 29 February acquisition completing on 28 February (§188 Abs. 3 BGB analog) — so a Berlin
  rendering that crosses midnight cannot flip an exemption (pinned by test). Boundary trios
  (second below / at / second beyond) run under both the winter and the summer clock.
- **Self-transfer**: carried slices keep their original acquisition instants (ticket 16), so
  the destination's disposal is exempt when purchase-to-sale exceeds the year — pinned by
  test. The destination needs no separate keep; the confirmation was the classification.
- **Freigrenze** (§23 Abs. 3 Satz 5 EStG): the limit is read per year from the statutory
  store; below it the whole Gesamtgewinn is free, at or above it (the statute says *weniger
  als*) the full amount is taxable — tested one cent below, at, and one cent above, and
  against a custom per-year value (600 €) to prove no constant hides in logic. A year whose
  limit is unset refuses by name (`StatutoryValueUnsetError`). Losses net within the year
  before the limit is judged.
- **Headroom or overshoot**: the `FreigrenzeVerdict` states `headroom_eur` below the limit and
  `overshoot_eur` at or above it, plus the resulting `taxable_gain_eur` — never left to
  arithmetic.
- **Tax Year by Berlin local date**: `fx.event_date` — the same clock as every reference-rate
  lookup — buckets each disposal; a sale in the last UTC hour of December belongs to the new
  German year (both sides tested).

Decisions worth recording:

- **Valuation states what the reference-rate universe can state** (ADR-0017): the numéraire by
  quantity, foreign cash by its own daily rate, a stablecoin by its peg's. Proceeds follow the
  consideration *received* (a spend, whose consideration left the ledger, is valued by what
  was given); splitting one consideration across several out-legs would need relative market
  values, so it is None — mirroring the lot engine's single-acquisition rule. A value needing
  a crypto price (ticket 18) makes the disposal **awaiting valuation**: named in the report,
  and while a *counted* gain awaits one the year states no total and no verdict. An exempt
  disposal awaiting valuation blocks nothing — it cannot move a total it is excluded from.
  Only the requested year is valued; another year's disposal costs no rate lookup and cannot
  fail over one. A genuine rate gap inside the year propagates as fx's own
  `RateUnavailableError` — a named, Admin-actionable condition, distinct from ticket 18's
  awaited machinery.
- **A kept windfall's disposal falls outside §23** (no Anschaffungsvorgang, BMF letter of
  10.05.2022): its consumption is visible wearing `without_consideration`, its proceeds are
  stated, and no gain exists to state — excluded from the total without blocking the verdict.
- **A disposal consuming an Opening Balance is flagged** `rests_on_estimate` (ticket 15's
  promise), so reports can say which figures rest on an assumption.
- **Fees charged against the disposal leg are its costs** (ADR-0011) — closing the loop
  ticket 19 left open ("charged against the disposal it is that disposal's cost") — pro-rated
  over consumptions like proceeds. The basis-source vocabulary the engine reads
  (`lots.ESTIMATE`, `lots.WITHOUT_CONSIDERATION`) is now exported by the module that mints it.
- **Nothing is persisted and no endpoint exists**: the engine re-derives per call — FIFO has
  no shorter memory — and the report lifecycle, staleness stamping (the fingerprint mechanism
  ADR-0014 reserved for reports) and any UI belong to tickets 23–25. `tax_treatment`'s
  import-scan pin now names exactly the lot engine and this module.
- Two-axis review fixes folded in: the requested-year filter before valuation (an out-of-year
  disposal could previously crash the report over a missing rate), the shared
  `never_enters_cost_basis` / `lots.grouped` / basis-source constants instead of duplicated
  strings and shapes, and the summer-clock and leap-day threshold tests. Deliberately not
  taken: computing detail for a year whose Freigrenze is unset (an unset statute is
  Admin-fixable configuration and the refusal names it — unlike ticket-18 valuations, which
  the Admin cannot enter), and a bundled valuation-context object for the internal
  `engine, source, instruments` parameters.
- No version bump — releases have not started; like tickets 09–19 this rides as `feat:` until
  one is cut.
