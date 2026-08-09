# 25 — Pre-flight blockers

**What to build:** The app refuses to finalise a report while it already knows something is wrong, and each blocker links to the screen that resolves it. The Admin may override, and the override is recorded on the report itself.

**Blocked by:** 23

**Status:** ready-for-agent

- [x] Blockers include unmatched transfers, unpriced Instruments with activity in the year, lots with unresolved shortfalls, unacknowledged Instruments with activity, and missing statutory configuration for the year
- [x] Later tickets can register further blockers without changing the finalisation flow
- [x] Each blocker links to the screen that resolves it
- [x] Finalisation is refused while any blocker is unresolved
- [x] An override requires an acknowledgement, which is recorded on the report and shown wherever the report is

## Comments

Implemented. The registry is `services/preflight.py`: a `Blocker` (kind, detail sentence,
`resolve_path`, count) and a `CHECKS` tuple of check functions, each `(engine, year) → Blocker |
None`. `services/reports.finalise` reads only `preflight.blockers(engine, year=…)`, so a later
ticket registers a further blocker by appending one function to `CHECKS` — tested by registering a
fake check and watching the unchanged flow refuse over it. Tests sit at the HTTP seam over real
Postgres (tests/test_preflight.py).

The five checks, each scoped to what can move the report year's figures:

- **unmatched_transfers** → `/transfers`: transfer legs up to the end of the year no confirmed
  match carries (services/transfer_matches.matching_overview), excluding legs standing ignored or
  dangerous — those never enter the cost basis (ADR-0012), so there is nothing to explain.
- **unpriced_instruments** → `/instruments`: Instruments the price chain answers for (ticket 18)
  with no stored last-known price and activity in the year. This made finalisation stricter than
  ticket 23 shipped it — test_reports' round trip now stores a quote first. The check's universe
  is the crypto chain's, the only pricing that exists yet; when securities pricing arrives
  (ticket 45) its ticket extends or registers alongside this check.
- **lot_shortfalls** → `/transactions`: disposals up to the end of the year exceeding the lots
  their Accounts hold. The judgement is the §23 engine's own — a new
  `section23.lot_shortfalls(engine, through_year=…)` enumerates every gap over the same replay and
  private-sale rule `year_report` refuses over, keeping `tax_treatment` readable by tax engines
  alone (the guard test caught the first draft importing it from preflight).
- **unacknowledged_instruments** → `/inbox`: arrivals up to the end of the year nobody has
  classified — the inbox's own criteria bounded by the year (repositories/preflight).
- **missing_statutory_configuration** → `/settings/statutory`: `statutory.missing_for_year`, the
  question that module was already holding for this ticket.

Finalisation answers 409 with `{message, blockers: [{kind, detail, resolve_path, count}]}`. The
override is `POST /reports/{id}/finalise` with `{"override": {"acknowledgement": "…"}}` — a
non-blank sentence, enforced by pydantic and by CHECKs on the new `report` columns
(`override_acknowledgement`, `overridden_blockers`, migration b2f2722a3d33): the two travel
together, only on a final report. The overridden blockers are frozen as JSON at the moment of the
override and answered verbatim — like `figures` — in both the listing and the detail; a clean
finalisation records nothing even when an acknowledgement was offered. Generation is unchanged:
it already refuses over shortfalls and unset statutory values, so blockers mostly open when the
ledger moves under a draft (tested by deleting the purchase behind a sale).

Two judgements the review surfaced, both deliberate: a transfer pair the Admin *rejected* keeps
its legs unmatched and keeps blocking — the movement stays unexplained, which is the point, and
the override with a written acknowledgement is the designed exit for a transfer that genuinely
left the Admin's estate. And the blocker checks read the present before the flip lands in its own
transaction; an edit slipped between the two is accepted as negligible on a single-Admin instance
(the same judgement ticket 23's generation makes of its ABA window), documented on
`services/reports.finalise`.
