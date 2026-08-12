# 23 — Report lifecycle and staleness

**What to build:** Generating a report freezes its figures together with a fingerprint of the inputs that produced them. A report moves from draft to final, a final report never changes, and the Admin is told when the data underneath one has moved.

**Blocked by:** 21, 22

**Status:** done

- [x] Generating a report stores the computed figures and a fingerprint of the inputs
- [x] A report moves draft → final; a final report is immutable
- [x] Regenerating creates a new report and never mutates an existing one
- [x] A report whose fingerprint no longer matches current data is flagged stale wherever it is shown
- [x] The staleness notice names what changed, by input class and count
- [x] The fingerprint covers statutory configuration, so correcting a rate marks dependent reports stale
- [x] A final report is never silently recomputed; regeneration is an explicit action
- [x] Deleting a transaction a final report depends on is blocked with an explanation, or marks the report stale — never silently changes a finalised figure

## Comments

Implemented. One migration — the `report` table (`id`, `year`, `status` draft/final, `generated_at`,
`finalised_at`, `figures` as JSONB, checks holding the status vocabulary, `final ⇔ carries its
instant`, and the statutory era bound). The fingerprint is ADR-0014's `input_fingerprint` table
and class vocabulary reused under the report's own subject (`report:<id>`) — the reuse that ADR
and the ticket both call for; the comparison behind every staleness verdict now lives once, in
`repositories/fingerprints.drifted`, with the lot materialisation's `services/lots.drift`
delegating to it. Endpoints: `POST /reports` (generate a draft for a year), `GET /reports` and
`GET /reports/{id}` (both wearing the staleness verdict), `POST /reports/{id}/finalise`. Tests
sit at the HTTP seam over real Postgres with rates through the reference-rate port's fake
(tests/test_reports.py).

How each criterion is held:

- **Generation freezes figures + fingerprint**: `services/reports.generate` computes the year's
  §23 (21) and §22 (22) figures, serialises them float-free (decimals as fixed-point strings,
  instants ISO-8601) into `figures`, and stamps the fingerprint in the same transaction that
  inserts the row. The engines read on their own snapshots — and a valuation may fetch rates
  mid-computation — so generation brackets them: the fingerprint taken before must still hold at
  the stamping instant, else a named `GenerationRacedError` refuses (409) rather than stamping a
  fingerprint the figures may not have seen. A remaining ABA window (an edit made and exactly
  reverted between brackets) is accepted as negligible on a single-Admin instance.
- **Draft → final, immutable**: the flip is one SQL `UPDATE … WHERE status = 'draft'`, so it can
  never happen twice; a second finalisation is 409, and no code path updates `figures`, `year`
  or `generated_at` at all.
- **Regeneration is a new report**: `POST /reports` only ever inserts; tested that the earlier
  report keeps its id, status and byte-identical figures while the new one carries the moved
  ledger's totals.
- **Stale wherever shown, naming class and count**: listing and detail both compute
  stored-vs-current on one REPEATABLE READ snapshot and answer `stale` plus `changed_inputs`
  (input class, stored count, current count). Tested for a post-generation trade (counts 2 → 3)
  in both surfaces.
- **Statutory coverage**: the class vocabulary already digests `statutory_value`; tested that
  correcting the §23 Freigrenze — on a 2030+ year, keeping the migration-seeded rows pristine —
  marks the report resting on it stale naming `statutory_configuration`.
- **Never silently recomputed**: reads answer the frozen JSON verbatim; a stale final report
  states its old figures beside the staleness, and only an explicit regeneration computes anew —
  onto a new report. Tested.
- **Deleting a depended-on transaction**: the permitted "marks the report stale" branch — the
  ledger stays editable (no FK leaves `report`, deliberately), the finalised figures stand
  untouched, and the fingerprint mismatch names the loss (counts 2 → 1). Tested against a final
  report.

Decisions worth recording:

- **The rates input class stays empty, now saying why**: its "not yet built" comment predated
  ticket 17. The reference-rate store is append-only and immutable (ADR-0017) — a fetch only
  ever adds coverage, so no stated figure can change under it — which is why generation may
  fetch rates mid-bracket without tripping the race check. ADR-0014's "the rates used" wording
  is satisfied in spirit by that immutability; prices (18) point the entry at rows when they
  arrive, being corrections-capable.
- **The ECB source becomes a dependency** (`rates.get_reference_rate_source`, mirroring
  `db.get_engine`) so the router reaches the port and tests bind the fake — the first HTTP
  surface to need rates at all.
- **No seed step**: a report is the Admin's explicit act frozen at generation time, not fixture
  data — and the seed sets no statutory limits, so generation there would refuse by design.
- **No figure-presentation UI**: the lifecycle's surface is the API; form-shaped sections,
  CSV/PDF and the blockers screen are tickets 51, 24 and 25.
- Two-axis review fixes folded in: the era bound read from `statutory.FIRST_YEAR` instead of a
  fresh literal, the flag-argument overview builder split, `Refusal` imported from the
  repository as the transactions router does, and the stale rates comment above. Deliberately
  not taken: moving `fingerprints.drifted` out of the repositories layer (ADR-0014 blesses the
  one shared home beside the digest vocabulary) and deduplicating the per-file test helpers
  (the repo's self-contained test-file convention, as ticket 22 already recorded).
- No version bump — releases have not started; like tickets 09–22 this rides as `feat:` until
  one is cut.
