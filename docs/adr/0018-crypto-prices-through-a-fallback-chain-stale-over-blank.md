# Crypto prices through a fallback chain, served stale over blank

## Status

accepted

## Context

Crypto Instruments need market prices for holdings and unrealised results, but no single free
provider covers everything: each keys assets on its own identifiers — CoinGecko on coin ids and
asset-platform slugs, DefiLlama on chain slugs — and each has its own coverage gaps, rate limits
and outages. A price display must also survive every provider failing at once without showing a
blank or, worse, a zero: a zero is a statement about value, and a blank hides that a value was
ever known.

## Decision

Crypto prices come through **one port with a documented chain of providers** (ADR-0008), tried
in order: **CoinGecko first** — it quotes EUR directly — **then DefiLlama**, quoting USD,
converted by the reference-rate rule (ADR-0017). Each provider answers for the Instruments it
can identify by the ledger's own identity attributes — chain and contract address for a token,
symbol for a native coin; the ones it cannot map fall through to the next provider. **No
provider-specific identifier being absent may exclude an Instrument from pricing** — unmapped
means "not covered here", never an error and never exclusion.

What a provider answers becomes the **stored last-known price** — one row per Instrument
carrying the price in EUR, the source that answered and the instant the quote represents. When
every provider fails or passes over an Instrument, that stored price is **served clearly
labelled stale**, with its source and age on display; an Instrument nothing has ever priced is
named **unpriced**, never valued at zero. Staleness is always reported by **naming the affected
Instruments** — one provider being down while another answers is not an outage of anything but
that provider.

Failures are named: a **rate limit is its own condition**, distinct from an outage, because the
two demand different responses — waiting versus investigating.

**Daily closes** are stored per Instrument and day with the same source attribution, populated
by a backfill over a chosen range; the first stored close for a day wins forever, so history
never silently shifts under a chart.

The chain prices only what the reference-rate universe cannot: stablecoins route to their peg's
daily rate (ADR-0017), and dangerous or everywhere-ignored Instruments may never acquire a price
source (ADR-0012).

## Considered Options

- **One provider, chosen well.** Rejected: any single free tier has gaps and limits, and its
  identifier scheme becomes a de-facto requirement on the ledger — exactly what the
  no-identifier-excludes rule forbids.
- **Keying providers on symbols.** Rejected: two tokens legitimately share a ticker (ADR-0010),
  and a symbol-keyed lookup would hand one token the other's price. Tokens are keyed on chain
  and contract everywhere; only native coins, whose symbol is their identity, map through it.
- **Serving nothing when providers fail.** Rejected: a blank cannot be told from "never priced",
  and the next candidate — zero — is a false statement. A stale figure with its age and source
  is the honest answer.
- **A staleness threshold on stored prices.** Rejected: staleness here is an outcome — "the
  chain could not answer just now" — not an age judgement, so the label derives from the refresh
  that just happened rather than from a configurable cutoff.

## Consequences

- Portfolio valuation (later tickets) can consume one report shape — fresh, stale or unpriced
  per Instrument — and inherits the never-zero rule without its own guards.
- Extending coverage is one mapping line in a provider port, or one new provider appended to the
  chain in `prices.py`; core code learns no provider's name (ADR-0008).
- A rate-limited primary degrades to the fallback silently and reports the condition by name;
  the Admin sees which providers struggled and which Instruments are affected, never a blanket
  outage.
- Stored daily closes make charts and historical valuations independent of any provider being
  up at read time.
