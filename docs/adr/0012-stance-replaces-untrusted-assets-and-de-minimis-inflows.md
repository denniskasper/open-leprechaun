# Stance replaces Untrusted Assets and De-minimis Inflows; unrecognised inflows default to deny

## Status

accepted — supersedes v1's ADR-0009

## Context

v1 needed two mechanisms because the failure had two shapes: an asset-wide flag for tokens that
are junk in their entirety, and a value threshold for a legitimate asset whose wallet receives
dust-spam. The flag could not serve the second case, because marking the asset would zero out the
genuine holding alongside the spam.

Both existed largely because assets were keyed on symbol, so a same-ticker impostor could inherit a
real project's identity and price. ADR-0010 removes that cause. What remains is the real problem:
things arrive at a self-custody wallet unasked, and some of them are dangerous to touch.

## Decision

A single **Stance** per Instrument: `unacknowledged`, `kept`, `ignored`, `dangerous`. New
Instruments arrive `unacknowledged`, and an inflow of one is **recorded but mints no Tax Lot** —
it waits in an inbox until the Admin classifies it. The default is deny rather than accept.

`dangerous` applies to an Instrument globally, because a token whose approval drains a wallet is
dangerous everywhere. `ignored` and `kept` apply **per Account**, which is what lets a real holding
bought on one venue coexist with dust of the same Instrument sprayed at another — the case that
forced v1 to have two mechanisms.

Acknowledging an unsolicited inflow asks whether it was received for a counter-performance,
defaulting to no.

## Considered Options

- **Keep the asset-wide flag plus a value threshold,** as v1 did. Rejected: two mechanisms for one
  problem, and the threshold silently accepts anything below it.
- **Heuristic detection.** Rejected in v1 after prototyping and rejected again: the obvious signals
  match legitimate holdings that merely arrived from untracked sources. Heuristics may later order
  the inbox; they may never decide it.

## Consequences

- The failure mode is an item waiting in an inbox, not a holding silently valued at zero. That is
  the whole point of the change.
- The transaction is always recorded whatever the stance, so balance reconciliation continues to
  see the truth; only lot creation and valuation are affected.
- v1's materiality caveat still holds and still matters: an inflow valued at zero because nothing
  prices the Instrument is *unknown*, never immaterial, and must never be discarded on that basis.
- Ignored and dangerous positions stay **visible** with a warning. The holding genuinely exists
  on-chain, and hiding it would be a different kind of lie.
