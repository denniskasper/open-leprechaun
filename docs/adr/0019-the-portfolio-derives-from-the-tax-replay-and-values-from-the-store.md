# The portfolio derives from the tax replay and values from the store

## Status

accepted

## Context

The Holdings view (ticket 20) states, per (Account, Instrument): quantity, cost basis, current
value and unrealised result. The basis must be the tax engines' own answer — a portfolio summing
inflows would drift from the report the moment FIFO consumed a lot — and the view must respond
within a second, which rules out live provider I/O on the request path. The persisted `tax_lot`
table alone cannot answer "what remains": it holds every minted lot, and what disposals consumed
of them exists only inside the derivation.

## Decision

The lot engine's one replay (ADR-0014) answers one more question: alongside the lots it mints
and what each consuming leg took, the `Derivation` now returns **what remains in every
(Account, Instrument) FIFO queue** at the end of the pass. Holdings read their basis from these
remaining slices — the same pass the disposal engine (ticket 21) reads — so the portfolio and
the tax report cannot disagree by construction. Quantity itself is the ledger's own sum of legs,
whatever the stance, so an ignored, dangerous or unacknowledged Position stays visible; where
the remaining lots cannot state a basis, the Position says which way — a valuation still
awaited, or quantity no lot ever vouched for — never a partial sum posing as the whole.

Values come **only from the store**: the numéraire by identity, foreign cash and pegged
stablecoins by the **latest stored reference rate** within the publication lookback (ADR-0017),
crypto by the stored last-known price with its source and age (ADR-0018). The request path
performs no outside I/O at all — no price provider and no rate fetch; conversions made
elsewhere (the tax engines, the display-rate endpoint) keep the rate store warm — and a
Position nothing stored can value is marked unpriced and excluded from totals.

The **DisplayCurrency** (`CONTEXT.md`) is served beside the figures as one latest reference
rate; every figure crosses the API in EUR and the client multiplies for presentation alone, so
no tax figure can ever pass through the display choice.

## Considered Options

- **Reading the persisted lot table and re-consuming it against out-legs.** Rejected: it
  re-implements FIFO consumption a second time — transfer carries, unvouched shortfalls and all
  — and two implementations of the same rule will eventually disagree.
- **Materialising a remaining-holdings table beside the lots.** Rejected for now: the replay is
  pure Python over an already-read ledger and fits the one-second budget with two orders of
  magnitude to spare; a second materialisation buys nothing but another fingerprint to keep
  honest.
- **Refreshing crypto prices during the holdings request.** Rejected: the provider chain's
  latency and failure modes (ADR-0018) would ride on every page load; a stored price with its
  age on display is the honest fast answer, and refresh remains one explicit call away.
- **Fetching a missing reference rate during the holdings request.** Rejected: on any day
  before the ECB publishes — every morning, all weekend — the store lacks today's row, so
  every view would cost one network round-trip per foreign currency held and block on the
  source being up. Reading the latest stored publication, its date on display, keeps the
  one-second budget structural; `portfolio()` takes no rate source at all, so the guarantee
  is enforced by signature.
- **Converting to the DisplayCurrency server-side.** Rejected: it would put a presentation
  choice inside API figures that downstream code might mistake for tax-relevant values; serving
  EUR plus one rate keeps the boundary structural.

## Consequences

- Holdings, disposals (21) and income (22) all read one derivation; a fix to FIFO or transfer
  carrying corrects all three at once.
- The holdings request costs one ledger replay per view. Should the ledger outgrow the budget,
  the remedy is a remaining-holdings materialisation under the existing fingerprint mechanism
  (ADR-0014) — an optimisation invisible to callers of `services/holdings.portfolio`.
- The snapshot views (ticket 54) and health panel (55) inherit a valuation that never blocks on
  a provider and a basis that never contradicts the report.
- Every marker the view shows — dangerous, ignored, unacknowledged, unpriced — and both basis
  gaps are stated by the service, so any future consumer (CSV export, another UI) inherits the
  never-zero, never-hidden rules without its own guards.
