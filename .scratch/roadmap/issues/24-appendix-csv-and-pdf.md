# 24 — Appendix, CSV and PDF

**What to build:** Every headline figure is backed by the line items that produced it, exportable in a machine-readable and an archival form that agree with each other.

**Blocked by:** 23

**Status:** ready-for-agent

- [x] Each disposal line shows acquisition and disposal dates, quantity, basis, proceeds, fees, holding period, exempt or taxable, category, and the lots consumed
- [x] Lines resting on an estimated basis are marked, and the total exposed to estimation is stated
- [x] Exempt disposals remain visible in the appendix even though excluded from the total
- [x] Export as CSV and as PDF, both containing the same figures
- [x] Rounding is applied at presentation and statutory boundaries only, per one documented rule
- [x] No account-derived figures appear in any fixture committed to the repository

## Comments

Implemented. No migration — the appendix is presentation over a report's **frozen figures**
(ticket 23), never a recomputation, so a final report's appendix is as immutable as the report.
Endpoints: `GET /reports/{id}/appendix.csv` and `GET /reports/{id}/appendix.pdf`, both
downloads. Tests sit at the HTTP seam over real Postgres (tests/test_appendix.py), figures all
invented for the scenario.

How each criterion is held:

- **Disposal lines**: `services/appendix.build` renders one row per consumed lot slice — the
  disposal's rows are its lots — each carrying acquisition and disposal dates (Europe/Berlin,
  the tax-year clock), quantity, basis, its share of proceeds and fees, holding days,
  exempt/taxable/outside-§23/awaiting-valuation treatment, and category. The engine now states
  each slice's fee share (`section23.Consumption.costs_eur`, the same pro-rating as proceeds)
  so the appendix reads it from the frozen JSON instead of re-deriving it.
- **Estimation**: a slice whose `basis_source` is the Opening Balance estimate wears an
  `estimated` mark, and the summary states `section23.gain_on_estimated_basis_eur` — the
  counted gains resting on estimates, summed exact and stated by the presentation rule.
- **Exempt visible**: exempt slices render in full with `treatment = exempt`; the summary's
  totals are the frozen headline figures, which never included them.
- **CSV = PDF**: both exports render one `Appendix` value whose every cell and summary entry
  is a string formatted exactly once — two renderings of the same strings cannot disagree.
  Tested by extracting the PDF's text (pypdf, dev-only) and asserting every summary value and
  every cell appears. Labels (symbol, platform/account) resolve at export time — presentation
  over the frozen ids, with an `instrument:7` fallback where a label no longer resolves.
- **One rounding rule**: `services/rounding` is now the documented rule — euro amounts
  half-even to the cent, only at statutory boundaries and presentation, plus the named
  per-unit-price exception — and the former scattered `_CENT`/`ROUND_HALF_EVEN` sites
  (section20, section23, lots, holdings) all import it, so the rule lives once.
- **Fixtures**: every number in the new test file is invented; nothing derives from any
  account.

Decisions worth recording:

- **Frozen figures, not live data**: an appendix computed live could disagree with the
  headline it backs whenever the ledger moved after generation; staleness is already the
  report's own verdict and needs no second mechanism here.
- **fpdf2 (pinned) renders the PDF**; core-font cp1252 with replacement for characters beyond
  it — only labels can carry such a character, every figure is digits, so a replacement never
  touches a number. A report a figure crosses into stays byte-exact regardless.
- **`amount_eur` is one column** for what a line put toward its section's figure — a §23
  gain, a §22 market value on receipt, a §20 counted amount — so every section shares one
  line shape and the CSV stays one table.
- A report awaiting valuation exports honestly: the affected lines say `awaiting_valuation`
  and the summary states the condition instead of a number. Tested.
- Two-axis review fixes folded in: the counting rule now lives once (`section23.counts`
  takes the two frozen facts, engine and appendix both call it), the 15-wide positional line
  tuples became a `Line` dataclass with `COLUMNS` derived from its fields (a column can never
  drift from the cells beneath it), a report frozen before the consumption fee-share existed
  fails loudly on export instead of rendering a silently blank fees column (pre-release, such
  a report is regenerated, not migrated), and the PDF-agreement test now checks multi-word
  cells word by word instead of skipping them. Deliberately not taken: a lot identifier in
  the appendix — the derivation's slices carry none, and a lot is named here by what the BMF
  letter's wallet-based FIFO defines it by (Account, Instrument, acquisition); the estimation
  exposure staying a sum over *counted* gains — an exempt estimated line wears its mark but
  exposes nothing the headline counted; and a CONTEXT.md entry for "awaiting valuation",
  which predates this ticket in the engines' vocabulary.
- No version bump — releases have not started; like tickets 09–23 this rides as `feat:` until
  one is cut.
