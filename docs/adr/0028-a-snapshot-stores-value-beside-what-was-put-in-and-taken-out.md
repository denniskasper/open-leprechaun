# A snapshot stores value beside what was put in and taken out

## Status

accepted

## Context

The value chart (ticket 54) shows how the portfolio developed. A series of values alone cannot do
that honestly: a deposit raises the line exactly as a gain does. The chart has to keep apart what
the Admin moved across the ledger's edge from what the holdings themselves did.

Two things were open: what counts as crossing the edge, in a ledger of balanced legs that has no
"deposit" type; and whether that figure is derived when the chart is read or stored when the
value is.

## Decision

A **Portfolio Snapshot** is one stored row per Europe/Berlin date — the day's latest measurement —
holding the value of every counted Position beside the **cumulative contributions and
withdrawals** of the ledger as it stood at that moment. The series ends in a live measurement made
by the same function, never stored.

A **contribution** is value that arrived from outside the ledger: a transfer in that no confirmed
self-transfer explains, and an Opening Balance. A **withdrawal** is value that left for outside: a
transfer out nothing matches, and a spend. Everything else is the portfolio's own doing — a trade
moves value between Positions, income and a futures result are what the holdings earned, a fee is
what they cost — so value less net contributions is the **result**, however it came about.

A flow is valued as of its own day (ADR-0024); an Opening Balance by the estimate the Admin
declared for it, which is what the ledger says the position cost. A flow nothing stored can value
stands outside the sums and is counted in the snapshot. A flow of a Position that never counts —
ignored, dangerous, unacknowledged — is left out with it, so both figures describe the same
holdings.

The request path reads the store alone, like Holdings (ADR-0019); only the scheduled task may ask
the rate source for a publication the store lacks.

## Considered Options

- **Deriving contributions from the ledger when the chart is read.** Rejected: a history imported
  later would move the contributions of every old point while their stored values stayed what the
  ledger knew then — and the gap between the two lines, which is the result, would be an artefact
  of the import. Stored together, an old snapshot stays what was known, and the next one carries
  the correction on both sides at once.
- **Counting income as a contribution.** Rejected: a dividend or a staking reward is what the
  holdings earned; counting it as money put in would hide exactly the return the chart exists to
  show.
- **Valuing an Opening Balance at its market value on its date.** Rejected: the close of a day
  that predates the available history is often not in the store, and the declared estimate is
  always there and is what every other figure about that position rests on.
- **Leaving contributions unstated while any flow is unvalued.** Rejected: one coin that arrived on
  a day without a stored close would blank the figure for good. The sum over what can be valued,
  with the count of what cannot beside it, is the totals' own rule (ADR-0019).
- **One snapshot per run.** Rejected: a run-now or a schedule firing hourly would make the series'
  density an accident of scheduling. One point a day, its latest, keeps ranges comparable.

## Consequences

- A snapshot is an observation, not a derivation: nothing rebuilds it, and it sits outside the
  input fingerprint. A ledger corrected afterwards shows as a step at the next snapshot — in value
  and contributions alike where the correction is a flow, in the result where it is not.
- The cumulative sums are valued afresh at every measurement, so a close or rate that reaches the
  store later moves a flow from unvalued into the sum at the next snapshot — a step in
  contributions with no movement behind it. Each snapshot's `unvalued_flows` is what tells the two
  apart, and the screen says so where a range's ends leave something out.
- The realised endpoint is not bound by the store-alone rule: it asks the disposal engines, which
  take the rate source as the report and the multi-year overview do.
- An unmatched pair of transfers between the Admin's own Accounts counts as a withdrawal and a
  contribution until the self-transfer is confirmed; the net is the same either way.
- The realised result (services/realised) is stated apart from all this: it sums the disposal
  engines' own gains without their tax rules, so it cannot disagree with the report about what a
  sale made.
