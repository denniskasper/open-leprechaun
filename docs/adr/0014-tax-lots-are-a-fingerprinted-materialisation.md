# Tax Lots are a fingerprinted materialisation, not a source of truth

## Status

accepted

## Context

v1 stored lot consumptions with the tax year, the taxability and the long-term flag **as columns** —
legal conclusions written to disk. It also intended the calculation to rebuild from the beginning
of time on every run with no incremental state that could drift. Both cannot be true: a stored
conclusion is a cache, and it goes stale the moment a transaction is edited, a statutory value is
corrected, or a classification changes.

The tension is real rather than academic. Recomputing every lot on every holdings render is the
honest model, but a full replay is the one place a sub-second budget actually bites.

## Decision

The transaction ledger is the only source of truth. Lots and their consumptions are **derived in
full**, from the beginning of time, and stored only so that holdings and reports need not replay
the ledger on every request.

Each materialisation records a **per-entity fingerprint** of the inputs that produced it — counts
and digests per input class, covering transactions, corporate actions, instrument classifications,
the rates used, and statutory configuration. A lot table whose fingerprint no longer matches the
ledger is detectable, and detectably stale rather than quietly wrong.

This is the same mechanism that marks a report stale, deliberately reused rather than duplicated.

## Considered Options

- **Persist lots and rebuild on a schedule,** as v1 did. Rejected: drift between rebuilds is
  undetectable, so a figure can be wrong with nothing indicating it.
- **Pure derivation, never stored.** The most honest option and rejected only on cost: a full
  replay per holdings render does not meet the response budget at the target scale.

## Consequences

- A persisted lot is authoritative only while its fingerprint matches. Nothing may read one without
  that check.
- The fingerprint must cover statutory configuration, not only transactions. Correcting a rate or a
  fund classification changes every figure resting on it while no transaction has moved — and that
  is precisely the correction most likely to matter.
- Corporate-action reversal becomes trivial: remove the event and rebuild. There is no lot state to
  unwind by hand.
