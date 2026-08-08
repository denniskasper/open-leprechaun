# 09 — Statutory configuration store

**What to build:** Every statutory constant the tax engines will need lives as per-year configuration with a cited source, editable in settings. No engine reads it yet — this ticket makes the values exist and be maintainable so that later tickets never hardcode one.

**Blocked by:** 03, 02

**Status:** ready-for-agent

- [x] Per-year rows cover: the private-sale exemption limit, the other-income exemption limit, the saver's allowance, the flat rate and solidarity surcharge, church-tax rates, per-category loss caps, and the annual base rate for advance lump sums
- [x] Each value records the source it came from, shown in the UI
- [x] Values are editable in settings and validated on entry
- [x] Filing status and church-tax election are settings that select which per-year values apply
- [x] A year with a required value unset is identifiable, so later tickets can refuse to compute it
- [x] No statutory value appears as a literal in application logic

## Comments

Implemented. One revision (`fc41e1dbaccd`) creates `statutory_value` and the singleton
`tax_election`; the vocabulary and the questions later tickets ask live in
`services/statutory.py`, the writes in `repositories/statutory.py`, and the UI at
`/settings/statutory` (nav section "Settings").

How each criterion is held:

- **Per-year rows cover everything named**: one row per (year, key), the twelve-key vocabulary
  pinned by a CHECK — the two Freigrenzen, both Sparerpauschbetrag variants, the flat rate,
  solidarity surcharge, both church-tax rates, the Basiszins, and one loss-cap key per
  §20 category (aktien / sonstige / termingeschaefte). The known values for 2024-2026 ride in
  with the migration itself (the EUR-numéraire precedent), verified against the statutes and
  BMF letters at build time, so a deployment can compute the first deliverable without anyone
  re-entering public law.
- **Each value records its source**: `source` is NOT NULL and CHECKed non-blank — a citation
  is not optional — and the UI renders it beside every value.
- **Editable and validated**: `PUT/DELETE /api/statutory/values/{year}/{key}` upsert and unset;
  the service's `entry_defect` refuses with a sentence what the schema would refuse with a
  constraint (negative value, rate above one, year outside 2009-2100), and the schema stands
  behind it. A rate of `25` where `0.25` belongs is refused at both layers, because that is the
  one silent mistake a percentage invites. Values are fixed-point end to end — NUMERIC,
  Decimal, strings in JSON, a JSON number is a 422.
- **Elections select, engines never compute**: the singleton `tax_election` row (born with the
  schema, default single / no church tax) carries filing status and the church-tax election;
  `saver_allowance_key` and `church_tax_rate_key` in the service are the selection — so no
  engine ever doubles an allowance or picks a rate in logic, and "none" yields no rate rather
  than a zero one.
- **A gap is identifiable**: `missing_for_year(engine, year)` answers with the required keys a
  year lacks — the question ticket 25 asks before letting a report finalise — and the overview
  carries the same list per year, worn in the UI as a caution ("N required values unset")
  against the signal-green "complete".
- **No literals in logic**: nothing outside the migration (data, not logic) and the tests
  states a statutory value; the engines to come read rows.

Decisions worth recording:

- **Loss caps are optional keys; absence means uncapped, never unknown.** The §20 Abs. 6
  Satz 5/6 caps (20 000 €) were struck retroactively for all open cases by the JStG 2024
  (BGBl. 2024 I Nr. 387), so no cap is seeded — but the store can express one per category
  per year the moment a legislature invents one, which is exactly story 163's point.
- **Verified against primary sources at build time**: §23 Freigrenze 1 000 € (VZ 2024+,
  Wachstumschancengesetz), §22 Nr. 3 Freigrenze still 256 €, Sparerpauschbetrag 1 000 / 2 000 €
  (JStG 2022), Basiszins 2.29 % / 2.53 % / 3.20 % for 2024/2025/2026 (BMF letters of
  05.01.2024, 10.01.2025, 13.01.2026).
- **Church-tax election is by region, not by rate** (`bavaria_bw` / `other_laender` / `none`) —
  the 8 % and 9 % are data on the year, so a Land changing its rate is an UPDATE.
- **Requiredness lives in the service, not the schema** — which keys a complete year needs is a
  question (`KEYS`), not a shape; the schema pins the vocabulary, units and bounds.
- **A year exists through its values**: the overview lists years that have rows; "Add year" in
  the UI is client state until the first value is stored, and the form says so. Later tickets
  ask `missing_for_year` for the report year directly, so an entirely-unset year is still
  identifiable where it matters.
- **English identifiers, German terms in copy** — matching the ledger's convention (the
  transaction vocabulary is English); the UI labels speak Freigrenze, Sparerpauschbetrag,
  Basiszins per the glossary, and each service key documents the statute it names.
- **Landed in two commits** (`483e169` API, web following) so ticket 19 — whose migration
  chains after `fc41e1dbaccd` and whose fingerprint digests `statutory_value(year, key, value)`
  — could land without waiting on the screen. Coordinated live with the ticket-19 session,
  including tax_election as a fingerprint-input candidate.
- Post-review fixes (two-axis review): the missing-keys computation collapsed into one helper
  read by both `missing_for_year` and the overview; the duplicated native-select styling became
  `components/ui/native-select.tsx`, now used by this screen and the Platform kind control; the
  UI's year bounds carry a comment naming the service constants they mirror, with the API's
  refusal as arbiter.
- No version bump — releases have not started; like tickets 10-15 this rides as `feat:` until
  one is cut.
