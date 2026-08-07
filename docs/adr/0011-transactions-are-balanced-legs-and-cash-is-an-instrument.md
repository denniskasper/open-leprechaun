# A Transaction is a set of balanced legs, and cash is an Instrument

## Status

accepted — supersedes v1's ADR-0010

## Context

v1's transaction row carried one asset, one quantity and a scalar EUR total, with **no currency
column anywhere**. The other side of a trade could not be represented, so v1 wrote a second row
and kept the two in step by convention. A cash balance could not be held at all: a quote balance
grew from deposits and was never consumed. Foreign currency could not be expressed, which is why
v1 could only note foreign-currency holdings as an unmodelled area rather than tax them.

The same shape produced three different treatments for economically identical things — a
stablecoin was a tracked asset with lots, a foreign currency was a caveat, and euro was a scalar.

## Decision

A **Transaction** is one economic event recorded as a set of **legs that balance** — what left,
what arrived, and what a fee consumed. More than two legs are expressible, so a fee paid in a
third asset is not a special case.

**Cash is an Instrument** like any other. EUR is designated the **numéraire**: it is the currency
every taxable figure is expressed in, and moving it is therefore not itself a disposal. Every
other cash Instrument — a foreign-currency balance no less than a stablecoin — is an ordinary
asset with an ordinary holding period.

A **fee attaches to the leg it was charged against, and its tax treatment is read from that leg's
regime** rather than from the transaction's type.

## Considered Options

- **Keep single-legged rows and a paired counter-leg,** as v1 did. Rejected: the pairing is
  convention rather than structure, and it still cannot express a currency or a cash balance.
- **Add quote columns to the transaction row.** Rejected in v1 and again here: it puts two assets
  on one row and breaks every consumer, from lot matching to holdings aggregation.
- **Keep cash as a balance per Account per currency.** Rejected: it is the choice that forced
  foreign-currency private sales to be a noted gap, and it makes cash the one holding that every
  query must special-case.

## Consequences

- Foreign-currency disposals fall out of the model instead of needing a second engine. This is the
  single largest behavioural gain from the change.
- The fee rule resolves a case no type-based rule handles cleanly: a currency-conversion fee is a
  cost of acquiring that currency, not a transaction cost of the trade it enabled.
- Every consumer reads legs, so nothing needs to know which side of a trade it is looking at.
