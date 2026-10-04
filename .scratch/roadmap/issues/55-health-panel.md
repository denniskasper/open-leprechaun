# 55 — Health panel

**What to build:** One page that answers whether the numbers on every other page are fresh — and when something is wrong, names it precisely instead of blaming everything.

**Blocked by:** 35, 42

**Status:** done

- [x] Per data provider: last successful call, last error, and rate-limit state
- [x] Per Connection: last sync, per-kind result and last failure message
- [x] Per scheduled task: last run and next due time
- [x] Database size and stored price-history row counts
- [x] A single failing provider is named along with the Instruments it affects — never reported as a total outage
- [x] Every problem shown links to the screen that resolves it

## Comments

Implemented as one migration (`c5f8d2e1a947`: `provider_status`, `provider_affected_instrument`),
the recording helper (`services/provider_calls.py`) around every provider call, the report
(`services/health.report`) behind `GET /health/report`, and the Health page rebuilt on it. The
public `GET /health` readiness probe is unchanged.

- **Per data provider.** Until now a provider's failure lived only in the report of the call
  that met it. The services that ask now record what the asking came to (ADR-0029): last answer,
  last failure with its sentence, and the present condition. The roster is what the instance is
  configured with — the crypto chain in order, the security price provider, the reference-rate
  source — so a provider nothing has asked yet reads "not asked yet" instead of being absent.
- **Rate limit** is its own state end to end: its own word, the caution tone, "run the update
  again later" — never the alarm an outage wears.
- **Per Connection.** Each adapter kind's recorded result with its failure sentence and the last
  success kept beside it; "last sync" is the latest result any kind recorded.
- **Per scheduled task.** Last run, outcome, error and next due, from the same state the settings
  screen reads. The panel also says when this instance does not answer schedules
  (`SCHEDULER_ENABLED` off) — ticket 42 left that unsaid.
- **Storage.** Database size, and the rows of crypto closes, security closes and published
  reference rates (a checked absence is not price history).
- **Named, never a total outage.** The affected Instruments are the price refresh's own finding,
  stored with it and restated by every refresh for every provider it could have asked. The page
  derives a list of problems, each on its own, under a headline that counts them and says
  everything not named is unaffected.
- **Every problem links.** Provider and task problems to Scheduled tasks (run the update again),
  a failing kind to Connections. When no report comes back at all the page asks the readiness
  probe which it was — API unreachable or database unreachable — the one problem no screen
  resolves.

Decisions worth recording:

- **A failing provider that left nothing stale is a caution, not an alarm** — another provider
  answered; it is worth knowing and not worth a red lamp.
- **A lone history failure does not call a provider down**: historical resolution records an
  outage only once `OUTAGE_PATIENCE` says it is the provider, because an unknown contract answers
  like one.
- **The reference-rate source names no Instruments** — it prices none; the problem says what
  waits on it instead.
- **Overdue tasks are shown ("Due now"), not counted as problems**: a long run legitimately
  delays the next, and a threshold would be a guess.
- **The report is the Admin's**; the probe stays public.
- **Left for later**: security *search* (identifier resolution) calls are not recorded — only
  pricing and reference rates feed figures a page shows.
- **Two-axis review folded in.** Spec axis: an answer now also drops what the earlier failure
  affected, so a later failure cannot resurface a stale list; restating the list tolerates two
  refreshes at once; a lone backfill failure is the Instrument's, as in historical resolution,
  while a rate limit is always the provider's. Standards axis: the two sections that can be
  empty use `EmptyState`; one map pairs each provider state with its word and tone; the state is
  `never_asked`, in the vocabulary the rest uses. Accepted as-is: a fallback that failed once and
  is no longer reached keeps its condition (as a caution affecting nothing) until something asks
  it again; a security price provider that configuration misnames is absent from the roster and
  speaks through its task's failure; "last sync" is the latest result a kind recorded, a
  Connection test included; an exception a refresh does not catch is recorded against the
  provider but restates no affected list.
- No version bump — rides as `feat:` like the tickets before it.

Tested at the API over real Postgres with port fakes (`test_health_report.py`), the page's pure
derivations (`pages/health.test.ts`), the client (`api/health.test.ts`). E2E:
`apps/web/e2e/health.spec.ts` — written, but not run in the implementing session: the browser
could not launch there.
