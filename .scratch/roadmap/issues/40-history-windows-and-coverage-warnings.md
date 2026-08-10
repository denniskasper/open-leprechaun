# 40 — History windows and coverage warnings

**What to build:** The Admin is told how far back each venue can actually reach, so "no trades found" is never mistaken for "no trades exist".

**Blocked by:** 35

**Status:** ready-for-agent

- [x] Each adapter declares its maximum lookback, shown per Connection in plain language
- [x] After a sync, the result states the period actually covered
- [x] The dashboard warns when a venue's coverage starts later than the earliest activity recorded elsewhere
- [x] The warning names the venue and links to the import path that would close the gap

## Comments

Implemented over ticket 35's declared capability (`lookback_days`, ADR-0008) and ticket 36's
minimal slice (`covered_days` in the sync result, which already satisfied the second criterion).
One migration (`b8d4f27c91a3`: `covered_from` on `connection_adapter_status`), one new endpoint
(`GET /connections/coverage-warnings`), a service/repository pair (`services/coverage.py`,
`repositories/coverage.py`), and two screens touched: the Connections settings page states each
kind's window, the Holdings page — the closest thing to a dashboard until ticket 55's health
panel — carries the warning.

- **Per-Connection wording**: the venues endpoint now serves `adapters: [{kind, lookback_days}]`
  (previously bare `adapter_kinds` strings), and each kind's line on the Connections page states
  it in plain language — "The venue serves the last 90 days of history.", or "…its full history."
  where a venue declares no cap. A kind a status or pairing names but the registry no longer
  serves states nothing rather than guessing.
- **Coverage is claimed by syncs alone**: a successful sync of a bounded-lookback kind stamps
  `covered_from = now − lookback` on the kind's status row; the upsert takes
  `LEAST(existing, new)`, so coverage once achieved only ever moves earlier and a later failure
  (or a mere credentials test, which pulls no history) never un-claims it. A failed pull, a
  refused commit and an unbounded venue all stamp nothing — NULL means "no bounded window
  claimed", which is exactly the set the warning may not rest on.
- **The warning judges per Account**, because the Account is where records land: its coverage
  starts at the *latest* `covered_from` over the kinds paired into it (full coverage begins only
  where the most limited window does — one warning per Account, not one per kind), pulled
  earlier by any activity already recorded there — history imported from a file is coverage no
  matter what claimed it, which is also what makes the warning disappear once the gap is closed.
  Earliest activity elsewhere is the minimum over every *other* Account's ledger Transactions,
  futures Fills and Funding Fees.
- **The warning names the venue** by its Platform and Account ("OKX · Trading: coverage starts
  …, but activity elsewhere starts … — older history at this venue cannot arrive by sync.") and
  links to the Imports screen, the path that closes the gap. It renders on Holdings above the
  totals, caution-toned, quietly absent while nothing warns — but a check that could not run
  says so, because for a warning whose job is surfacing silence, silence on failure would lie.
- **Tested at the established seams**: the API over real Postgres with port fakes
  (`test_coverage.py` — the gap warns with both instants stated; activity inside the window,
  older history already in the Account, a failed sync, a test alone and an unbounded venue all
  warn nothing; two kinds into one Account warn once at the most limited window) and the pages'
  pure functions (`describeLookback`, `describeCoverageWarning`).

Decisions worth recording:

- **"The dashboard" is Holdings for now.** No dashboard screen exists; Holdings is the landing
  view of everything held, and ticket 55's health panel can adopt or share the warning when it
  ships. The component is self-contained (its own query, absent when empty), so moving it is
  cheap.
- **Coverage start is computed at sync time, not derived from `last_success_at`**: the status
  timestamp also moves on a credentials test, and a test proves nothing about history — deriving
  coverage from it would claim a window nothing pulled.
- **Warning dates render as the instants' UTC days** — the horizon is approximate by nature
  (sync moment minus N days), and a deterministic date beats a timezone-shifted one.
- **Two-axis review folded in.** Spec axis: the warning sentence no longer claims "syncing
  reaches back to X" — when X came from history already recorded in the Account, syncing does
  not reach it, so the sentence now says "coverage starts X", true under both origins; and a
  failed warnings query renders its own caution line instead of passing for all-clear. Standards
  axis: `CoverageWarningResponse` gained the file's `.of` classmethod convention, and a doc
  comment stranded by the schema split moved back onto `venueSchema`. Accepted as-is: a paired
  kind that never synced does not narrow the Account's stated coverage start (the warning still
  fires; the Connections page already shows a never-synced kind as such), and the payload keeps
  `venue` and `connection_label` though the sentence renders neither — they tie the warning to
  the Connection at fault, which ticket 55's health panel will want.
- No version bump — releases have not started; this rides as `feat:` like earlier tickets.
