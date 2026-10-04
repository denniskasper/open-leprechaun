# 54 — Snapshots, value chart and allocation

**What to build:** The Admin can see how the portfolio has developed, without a deposit reading as a gain.

**Blocked by:** 20, 42

**Status:** done

- [x] Portfolio snapshots are taken on a schedule and stored
- [x] A value chart covers selectable ranges, backed by snapshots plus current live value
- [x] The chart distinguishes value change from contributions and withdrawals
- [x] Allocation charts cover asset class, Instrument and Platform
- [x] Each chart states how many positions it charts against how many are held
- [x] Positions below a threshold are grouped rather than dropped
- [x] Realised and unrealised results are shown separately
- [x] A figure that cannot be computed says so rather than showing zero

## Comments

Implemented (ADR-0028). One table (`portfolio_snapshot`), the snapshot service
(`services/snapshots.py`), the realised result (`services/realised.py`), two endpoints under
`/portfolio`, one more catalogue entry (`portfolio_snapshot`) and the `Ledger → Portfolio` screen
at `/portfolio`.

- **Snapshots on a schedule, stored.** The `portfolio_snapshot` task runs at 23:55 Berlin by
  default, after the day's price updates. One row per Europe/Berlin date; a later run of the same
  day replaces it. A run never fails over what it cannot value — its summary names it.
- **Value chart over selectable ranges.** `GET /portfolio/development` answers every stored
  snapshot and the live measurement, made by the same function and never stored; the screen offers
  1M, 3M, 6M, YTD, 1Y and everything, selected client-side. Today's stored snapshot gives way to
  the live point.
- **Value change apart from contributions and withdrawals.** Each snapshot stores cumulative
  contributions and withdrawals beside the value. The chart draws net contributions as a dashed
  step under the value line and splits the range's change into "put in or taken out" and "result".
  What crosses the ledger's edge: transfers in and out that no confirmed self-transfer explains,
  Opening Balances (at the declared estimate) and spends. Income, fees and trades are the
  portfolio's own doing.
- **Allocation by asset class, Instrument and Platform.** Client-side over the flat portfolio, like
  the Holdings grouping: ranked bars, an Instrument keyed by identity so two tickers never merge.
- **Charted against held.** Every allocation chart opens with "charts n of m positions held"; only
  a counted position worth more than nothing holds a share. The value chart's readout says "over n
  of m positions" for the point it shows.
- **Grouped, not dropped.** Slices under 2 % of the charted total collapse into one "n smaller"
  slice naming its members on hover; a lone small slice keeps its name.
- **Realised apart from unrealised.** `GET /portfolio/realised` sums the disposal engines' own
  gains — private sales, securities, closed futures — without their tax rules (Haltefrist,
  Freigrenze, Teilfreistellung, Vorabpauschale); unrealised is the Holdings total.
  `section23.disposals_through` was split out of `year_report` so the private sales answer without
  a Freigrenze configured, and values the basis of Haltefrist-exempt slices too; a windfall sold
  realises its whole proceeds.
- **Cannot be computed says so.** A value where something is held and nothing counts is null and
  reads "cannot be stated" and breaks the chart line; a realised kind none of whose events state a
  gain is unstated, one its engine refuses carries the engine's sentence, and the total is unstated
  as soon as one kind is; a figure covering only part says "over n of m".

Decisions worth recording:

- **The request path reads the store alone** (`fx.stored_value_eur`); only the scheduled run may
  fetch a reference rate the store lacks. The realised endpoint takes the rate source like the
  multi-year overview does.
- **A security arriving by transfer is an unvalued flow** — `fx.value_eur` states no close for a
  security at an event's day. It is counted and named; an Opening Balance is the way to state it.
- **No chart library**: inline SVG on the tokens, convention noted in `docs/agents/design.md`.
- **`formatMoneyExact` now places a negative sign where the locale does** — it sat between currency
  and digits before, which the Portfolio screen made prominent.
- **Left for later**: no backfill of snapshots for days before the task first ran; the ledger read
  for the flows and the one for the holdings are two database snapshots, a few milliseconds apart;
  each flow leg costs one store read per measurement, which is the first thing to batch should a
  ledger with very many transfers slow the screen; the securities kind refuses where the §20
  producer does (an unclassified fund, an unset Teilfreistellung rate), though the realised sum
  needs neither.
- **Two-axis review folded in**: the realised result no longer inherits §23's silences (exempt
  market-value lots, windfalls); a range counted back from a month's last day no longer spills into
  the next month; the range's change says when either end leaves something out; the value chart
  always states its coverage; Platform slices key on name and kind; the realised tile retries in
  place and Unrealised says when the holdings failed.
- No version bump — rides as `feat:` like the tickets before it.

E2E: `apps/web/e2e/portfolio.spec.ts`.
