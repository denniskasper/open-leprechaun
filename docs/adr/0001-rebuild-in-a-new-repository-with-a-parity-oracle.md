# Rebuild in a new repository, with v1's tax fixtures as a parity oracle

## Status

accepted

## Context

v1 produces correct figures for crypto private sales, other income and futures. What blocks
further work is structural: the entity that holds value is named for one of its kinds, an asset
is keyed on a string two unrelated tokens can share, a transaction cannot express a currency at
all, and the capital-income summary is shaped around futures with no room for a second source.
Each is a refactor; together they touch nearly every table.

## Decision

Rebuild in a new repository rather than refactor in place. v1 stays runnable as a read-only
reference and is never migrated — every source file that produced its data still exists, and v2's
shapes differ enough that a v1 database reader would map into structures that no longer exist.

The rewrite is constrained by a **parity oracle**: v1's statutory test fixtures are ported before
anything else, and v2 must reproduce v1's figures on them. Every divergence must be explained as
a deliberate fix, in writing, before it is accepted.

## Considered Options

- **Refactor v1 in place.** The honest alternative, and cheaper by raw effort. Rejected because
  the two structural changes that matter — balanced legs and a category-driven capital-income
  engine — each require rewriting the tax path, and doing both against live data with the old
  shapes still present is more dangerous than starting clean.
- **Rewrite without an oracle**, deriving the tax rules afresh from the statutes. Rejected: the
  tax engine is small, but retyping it with nothing to check against is how a rewrite quietly
  produces different numbers than the ones already filed.

## Consequences

- Historical figures must be re-established from their original sources, not inherited.
- The fixtures are the asset being carried over, not the code. They are ported first, and a
  divergence is a conversation rather than a test edit.
- v1's ADRs are carried into this repository where they still hold and explicitly superseded
  where they do not.
