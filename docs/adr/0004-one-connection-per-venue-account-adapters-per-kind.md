# One Connection per venue account; adapters and provenance stay per kind

## Status

accepted — carried from v1's ADR-0008

## Context

A single venue account uses one credential for everything it offers, but the data behind that
credential splits along lines German tax law cares about: spot activity feeds the private-sale
regime, futures feed capital income, securities feed capital income differently again.

## Decision

Unify at the **Connection** level — one Connection per venue account, holding one credential set
and a label, resolving to every adapter kind that venue supports. Test and sync act on the
Connection and report results **per kind**, so one kind failing never hides another succeeding.

Deliberately do **not** merge the adapter ports themselves: the pipelines are genuinely different
downstream, because the tax treatment splits exactly there. Imported data keeps a per-kind
provenance string, so deduplication keys and Account pairing stay distinct per kind.

## Consequences

- The Admin enters a key once per venue account, however many kinds it serves.
- A Connection records last success and last error per kind, which is what the health panel reads.
