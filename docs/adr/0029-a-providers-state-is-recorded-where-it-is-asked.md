# A provider's state is recorded where it is asked, and a refresh names what it left stale

## Status

accepted

## Context

The health panel (ticket 55) has to say, per data provider, when it last answered, what its last
failure was and whether it is rate-limiting — and which Instruments a failing provider affects.
Until now a provider's failure lived only in the report of the call that met it (ADR-0018): a
price refresh named its conditions and forgot them. Nothing could answer "is CoinGecko failing?"
without asking CoinGecko, and a health page that makes live provider calls to draw itself would
spend rate limit on being looked at.

Two things were open: where the record is written, and how "the Instruments it affects" is
decided.

## Decision

**The services that ask a provider record what the asking came to**, in `provider_status` — one
row per provider name holding the last answer, the last failure with its sentence, and the
present condition (`rate_limited` or `outage`, cleared by the next answer). The recording is one
helper around the call (`services/provider_calls.ask`); it never changes what a failure means to
the caller, and the health panel only ever reads.

The sentence kept is the port's own for a failure it named; anything else a provider raised is
recorded by its type alone (ADR-0003). The reference-rate source is recorded under the name of
who publishes the rate (ADR-0017) — the conversion rule already knows whose rate it is.

Historical price resolution records an outage only once it has decided the provider is down
(`OUTAGE_PATIENCE`): there an unknown contract answers like an outage, and one Instrument's
missing history must not put a provider in alarm.

**The affected Instruments are a price refresh's own finding**, stored with it: the Instruments
the refresh left without a fresh price while the provider was failing. Every refresh states this
afresh for every provider it could have asked — so a fallback that failed once and is no longer
reached keeps its condition (its last call did fail) but stops affecting anything.

## Considered Options

- **Probe the providers when the page is read.** Rejected: it spends rate limit on observation,
  makes the page as slow as the slowest provider, and reports the probe rather than the calls
  that actually priced something.
- **Wrap each provider in a recording decorator where it is composed.** Rejected: a provider is
  built without an engine and tests bind their own; recording at the call keeps the fakes plain
  and the record on the same database the call's result lands in.
- **Derive the affected Instruments on read** — every Instrument whose stored price names the
  provider as its source. Rejected: with a fallback chain the last source says who answered last
  time, not who failed this time; only the refresh knows what stayed stale.
- **A call log, one row per call.** Rejected: the panel needs the latest answer and the latest
  failure, not a history, and a log needs pruning nobody asked for.

## Consequences

- A provider nothing has asked on this instance reads "not asked yet" rather than healthy.
- A provider's state is as recent as the last thing that asked it — on a scheduled instance, the
  last price update.
- A new call site for a provider records by wrapping its call; one that forgets is invisible to
  the panel but breaks nothing.
