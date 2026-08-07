# Enforce the single-admin invariant at the database, not in the application

## Status

accepted — carried from v1's ADR-0006

## Context

The application is single-admin, so exactly one admin row may exist. In v1 both the startup
auto-setup and the setup endpoint used a check-then-insert with no database constraint. Running
more than one worker process against a fresh database made both see "no admin yet" and both
insert, after which login verified against a nondeterministically chosen duplicate. It could not
reproduce on a single-worker development server.

## Decision

Enforce the invariant in the schema: the admin table carries a column whose value is identical for
every row, under a unique constraint, so at most one row can exist. Setup paths catch the
resulting integrity error and treat it as "already configured" rather than crashing. Reads are
ordered deterministically as defence in depth.

## Considered Options

- **Application-level checks only.** Rejected: a check-then-insert cannot be made safe across
  processes without a database constraint. The race is inherent, not a coding mistake.

## Consequences

- A losing worker logs and continues instead of failing the boot.
- The same pattern is the right one for any other invariant that must hold across workers.
