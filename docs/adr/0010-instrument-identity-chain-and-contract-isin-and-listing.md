# Instruments key on chain and contract; securities key on ISIN with Listings

## Status

accepted — resolves the debt v1's ADR-0009 recorded

## Context

v1 keyed an asset on its **symbol**, unique across the whole table. A wallet identifies a token by
its contract address, so two unrelated tokens sharing a ticker collapsed into one row, and the
loser inherited the winner's price source, name and logo — minting lots with a cost basis
disconnected from reality. v1 recorded contract-address keying as the correct fix, rejected it as
disproportionate to a single-user tool, accepted the weak identity model as known debt, and named
it the decision most likely to be revisited.

A greenfield rebuild is exactly the moment it becomes proportionate.

## Decision

A crypto **Instrument** with a contract is keyed on **chain and contract address**. Native coins
key on symbol, because for them the symbol *is* the identity. A symbol is otherwise a display
label and a resolution hint, and is never authoritative for identity.

Securities key on **ISIN**. Because the same ISIN lists on several venues in several currencies,
a **Listing** — Instrument, venue, quote currency — is its own concept, and a price source points
at a Listing rather than at an Instrument. Because identifiers are reassigned by mergers and
redomiciliations, each Instrument keeps an **identifier history**, so a lot acquired under a
superseded identifier is not orphaned. WKN and ticker are lookup aliases only.

## Considered Options

- **Keep symbol keying and mitigate with flags,** as v1 did. Rejected: the mitigation is the
  problem — an entire domain concept existed only to work around a schema decision.
- **Treat ISIN as sufficient identity for securities.** Rejected: it says nothing about which
  market or currency produced a quote, and it does not survive a corporate action.

## Consequences

- Two Instruments sharing a symbol coexist, and a same-ticker impostor is simply a different
  Instrument that has borrowed nothing.
- This removes the *cause* of v1's Untrusted Asset concept. What remains is the Admin's stance
  toward junk, which is a different problem with a different solution (ADR-0012).
- Identity resolution must be able to say "I don't know which of these you mean" rather than
  picking. An unresolved Instrument is a normal state, not an error.
