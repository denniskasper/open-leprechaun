# An event is valued by the stored close of its own day, resolved on import

## Status

accepted

## Context

The tax engines value an event at the instant it happened: income at market value on receipt,
a disposal by the value of what arrived. The reference-rate universe states that for cash and
stablecoins (ADR-0017); for every other crypto Instrument the one valuation rule answered
"awaiting valuation". The price chain (ADR-0018) stores a last known price, but that is today's
price — valuing a past event with it backfills cost basis from the present, which is the wrong
figure with a confident face. Imported rows are where the gap arrives in bulk: an exchange
export states a staking reward's quantity and never its worth.

## Decision

A crypto event is valued by the **stored daily close of its Instrument for the UTC day of the
event's instant** — the day providers bucket their history by, so the close that actually
contains the event. The one valuation rule (`fx.value_eur`) reads that store and nothing else:
no provider I/O on a report path, and no close means awaiting valuation, never zero.

**An import fills the store on commit.** After the batch has landed, every leg only the chain
can price and that has no stored close is resolved through the chain: one history request per
Instrument and provider over the days still open, a day one provider leaves open falling
through to the next. A row *states its own price* when one whole side of an exchange is cash or
a stablecoin and the other side is a single position; its exchanged legs then want nothing.
Several positions against one sum need their relative market values and are priced like
anything else. Fees in a coin always want their close.

A row the chain could not price is **listed in the import result** with the Instruments left
open and each failing provider's named condition. The flag is derived, not stored: it is the
absence of a close. The scheduled crypto price update runs the same resolution over the whole
ledger, so a gap left by a rate limit settles itself; a backfill of the Instrument does it by
hand.

**The current UTC day has no close.** The first stored close wins forever, so a provider's
latest intraday point is never stored as one — by an import or by a backfill. An event of today
awaits its valuation until the day is over.

The closes an event rests on are a **fingerprinted input** (the `rates` class, ADR-0014): a
close arriving for a day one of the Instrument's legs happened turns an awaited figure into a
stated one, so reports stamped before it read stale. Closes for days nothing happened on feed
charts alone and drift nothing.

## Considered Options

- **A price column on the leg, written by the import.** Rejected: a second home for the same
  fact beside the close store, absent on hand-recorded events, and a figure the Admin could not
  re-derive. The store is already immutable — first stored close wins — which is what
  reproducibility needs.
- **Valuing at the last known price when no close exists.** Rejected: that is precisely
  "backfilled from today", and indistinguishable from a real figure once written.
- **Resolving at report time.** Rejected: provider latency and failure would ride on report
  generation, and a generation must stamp the inputs it actually saw.
- **Resolving inside the batch's database transaction.** Rejected: a rate limit would cost the
  import. Pricing is a consequence of the rows existing, not a condition of it.
- **Finer than daily.** Not now: the free tiers answer sub-daily points only for recent ranges,
  and a close per day is what the store already keys. A finer store can replace the lookup
  behind the same rule.
- **The Berlin calendar day**, as reference rates use. Rejected for closes: the ECB publishes
  per calendar date by convention, while a provider's daily close is a UTC bucket — asking for
  the Berlin date would read a close that ends before or after the event.

## Consequences

- §22 income, the basis of the lot it mints, and the proceeds of a crypto-for-crypto disposal
  are stated wherever a close is stored, for imported and hand-recorded events alike — the rule
  reads the store, whoever filled it.
- A purchase paid in anything but the numéraire still mints its lot awaiting a basis: the lot
  derivation states a cost only from numéraire legs, and extending it is its own change.
- Committing an import now reaches the price providers. Nothing a provider does fails the
  commit — a rate limit stops the run asking it, anything else it raises is its outage, and a
  run of outages stops the asking too — it leaves rows unpriced and says which provider
  struggled and how.
- What "the close of a day" is remains each provider's answer: the last point it holds for the
  UTC day, whose granularity varies with the range asked. Daily resolution is the precision
  claimed, no finer.
- Bare movements are priced too, so an unsolicited inflow nothing prices is named unknown
  before the Admin decides its stance (ADR-0012) rather than assumed worthless.
