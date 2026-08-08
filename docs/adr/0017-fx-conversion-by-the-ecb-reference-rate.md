# FX conversion by the ECB reference rate of the event date

## Status

accepted

## Context

Every tax figure is stated in EUR, but events arrive in other currencies — a trade settled in
USD, a stablecoin disposal, a dividend in CHF. The figures must be defensible years later: a
re-run of a report must reproduce the same numbers, and the choice of rate must rest on one
citable rule rather than whichever provider a chart happened to use. The rate source also has to
cover days with no publication — weekends and TARGET closing days — without inventing a rate.

## Decision

Every foreign-currency amount converts to EUR by the **euro foreign exchange reference rate**
published by the ECB — one canonical source, behind a port with a fake (ADR-0008). The rate used
is the rate of the **event date**: the Europe/Berlin calendar date of the event's instant, the
same clock that buckets tax years. Report time never picks a rate.

A date with no publication resolves to the **most recent publication on or before it**, at most
seven days back — enough to cover the longest TARGET closure run (four days) with margin, and
tight enough that a genuine data gap becomes an error naming the currency and date rather than a
silently stale figure.

Rates are stored **as published** — units of currency per one euro, against the date the rate
represents — and a stored row is never overwritten. A day the ECB published nothing for is
stored too, as a **checked absence**, once that day is past in Berlin — so the fallback answers
from the store rather than asking the source again, and a rate already stored for a neighbouring
day can never stand in for a publication the event date actually has. A conversion fetches only
when the store holds no answer for the event date itself, so re-running any conversion
reproduces the same figure exactly, whatever the ECB's feed would answer today. The rate and its
date travel with every converted amount, so a report can show its working.

**Stablecoins** are valued through this rule, not through a crypto price provider: a stablecoin
carries the currency it pegs, and its EUR value is the pegged currency's daily reference rate.
Provider coverage of stablecoins is poor, and an unpriced disposal books zero proceeds against a
real cost basis, manufacturing a phantom loss.

## Considered Options

- **A market-data provider's FX endpoint.** Rejected: provider rates vary by venue and moment,
  are revised silently, and carry no citation. The ECB reference rate is the rate German practice
  reaches for, published once per day and archived forever.
- **Interpolating across publication gaps.** Rejected: an interpolated rate is an invented one.
  The most recent prior publication is a real, citable figure, and the seven-day bound keeps it
  honest.
- **Converting at report time.** Rejected outright: the same disposal would change value between
  two runs of the same report.

## Consequences

- The conversion service is deterministic given the store, so tax engines built on it (21, 22,
  26) inherit reproducibility without their own rate logic.
- The pegged-currency mark on an Instrument is the routing rule ticket 18's price chain must
  consult before any crypto provider.
- An offline deployment converts nothing it has no stored rate for — it errors by name rather
  than inventing or reusing a stale figure.
