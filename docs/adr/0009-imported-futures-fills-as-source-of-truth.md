# Imported futures: immutable fills are the source of truth, positions are derived

## Status

accepted — carried from v1's ADR-0002

## Context

Some venues expose only individual fills — a side, price, size and fee at a timestamp — with no
position, no realised result, no leverage and no long/short indicator, and cap each query to a
limited window. Others expose considerably more.

## Decision

Store fills immutably, deduplicated on source and external identifier. Derive positions as a pure,
deterministic function of the *entire* fill sequence per symbol, rebuilt wholesale per source on
every sync rather than patched incrementally. Funding is fetched separately and attributed to the
position open at its timestamp. Manually entered and derived positions share one model and one tax
treatment; only their origin differs.

Where a venue exposes position side, reduce-only or per-fill realised result, derivation uses it
and is exact. Where it does not, derivation falls back to documented net accounting.

## Considered Options

- **Reconstruct positions in place without storing raw fills.** Rejected: mutating already-built
  positions across overlapping sync windows is stateful, easily corrupted, and not idempotent.
- **Store fills only and compute at report time.** Rejected: it forks the tax engine into a second
  futures path and a second representation in the UI.

## Consequences

- Re-syncing is idempotent: overlapping windows and repeated runs cannot double-count.
- A symbol whose fills do not reconcile — including any position whose opening fills predate what
  the venue still returns — is flagged for manual handling rather than guessed.
- Leverage and margin are unavailable from fills and stay unset; they do not affect the figures.
