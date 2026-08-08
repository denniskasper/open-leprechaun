# A confirmed self-transfer carries lots FIFO, the fee off the head

## Status

accepted

## Context

A confirmed self-transfer (ticket 16) carries the source Account's lots to the destination with
their original acquisition instants and bases — a self-transfer must not restart the Haltefrist,
and a Depotübertrag must preserve lot identity. Two questions have no single obvious answer and
must be pinned somewhere the tax engines can cite:

1. **Which lots move?** The moved parcel is whatever the source Account's FIFO queue yields at
   the withdrawal's instant, which can span several acquisitions.
2. **Which units did the shortfall consume?** When less arrives than left — a network or
   withdrawal fee burnt en route — some units, with their dates and bases, never arrive. FIFO
   does not say which units of the moving parcel the fee took; pro-rata across the parcel would
   be an equally defensible reading.

## Decision

The lot engine replays the ledger chronologically with a FIFO queue per (Account, Instrument):
minting in-legs push, out and fee legs consume from the head, and a confirmed match routes what
its out-leg consumed to its in-leg's Account. Each carried slice keeps its original
`acquired_at`, `basis_eur` and `basis_source` — an estimate stays an estimate, so disposals
resting on one stay flagged downstream.

**The shortfall burns from the head**: the missing units are taken from the oldest slices first
— under FIFO the earliest-acquired units are the first the parcel gives up — so the destination
never claims an older acquisition date than it can prove. The conservative side of the
indeterminacy falls on the taxpayer's claim, not the Fiskus's.

A pro-rated basis split is stated in cents with the exact remainder on the other part, so no
cent is invented or lost. The burnt portion's basis is not restated anywhere by this engine —
the ledger still holds the legs and the match, and the disposal engine (ticket 21) decides what
a transfer fee is for §23.

## Considered Options

- **Pro-rata burn across the parcel.** Defensible reading of the statute's silence; rejected
  because it splits every carried slice on every fee, multiplying lots without making any date
  claim safer — head-burn is at least as conservative and keeps slices whole.
- **Burn from the tail (newest first).** Rejected: the destination would keep the oldest dates
  in full, the aggressive side of an indeterminate question.
- **Carry the fee's basis into the surviving slices.** Rejected here: whether a transfer fee is
  acquisition cost, disposal cost or neither is ticket 21's question, and answering it inside
  the carry would hard-code one §23 reading into the lot table.

## Consequences

- One in-leg can mint several lots, so `tax_lot` is keyed `(leg_id, ordinal)` — identity is
  still derived, never assigned, and rebuilds stay byte-identical.
- What the source cannot vouch for carries nothing: a transfer out of an unlotted holding
  arrives without a lot rather than inventing an acquisition at the destination.
- Confirmed links are a fingerprint input class; a confirmation alone marks the lots stale and
  the next read rebuilds.
