# A multi-chain token is one Instrument with Deployments

## Status

accepted — amends ADR-0010

## Context

ADR-0010 keys a token on chain and contract, which makes the same issuer's token on two chains
two Instruments. An exchange balance is on no chain: the venue holds one balance and picks a
network only when it sends. Ingestion resolves an exchange record by symbol alone, so a deposit
that moved on one chain lands on whichever chain's Instrument happens to answer to the symbol.
Splitting them honestly would be worse: a send from an exchange on a chain other than the one its
balance was booked on would need a swap that never happened — a disposal that restarts the
Haltefrist and books a private sale.

## Decision

A token its issuer mints natively on several chains is **one Instrument**. Each chain's contract
is a **Deployment** — an identity of that Instrument, held beside it as ADR-0010's identifier
history holds a security's ISINs. An exchange Account holds the Instrument; a wallet Account,
whose chain is fixed, holds it on that chain's Deployment. Moving it between chains, or between
an exchange and a wallet, is a transfer and never a disposal.

Only the issuer's own deployments qualify, including those reached through the issuer's own
burn-and-mint transfer. A bridged or wrapped token is a claim on a bridge or custodian — a
different debtor — and stays its own Instrument.

The Admin attaches a Deployment; the ledger never merges by symbol or name. An unknown contract
still lands as its own Instrument, `unacknowledged`, and may be settled as a Deployment of
another only while it holds no lots.

The network a venue states for a transfer is recorded on it as a fact, beside its transaction
hash and counterparty address. In resolution it only breaks a tie between Instruments that answer
to the same symbol.

## Considered Options

- **One Instrument per chain, as ADR-0010 left it.** Rejected: an exchange balance must then sit
  on a chain it is not on, and every cross-chain send fabricates a disposal.
- **Merge automatically by symbol or by a price provider's asset id.** Rejected: it is the
  symbol keying ADR-0010 removed, and it would fold a bridged claim into the asset it claims.
- **Treat bridged tokens as the same asset.** Rejected: a different debtor stands behind each,
  and a swap between them is an exchange of one Wirtschaftsgut for another.

## Consequences

- A token's identities live in a `deployment` table — instrument, chain, contract — under a
  unique index over chain and lowercased contract, so one contract still names one Instrument
  across every chain; resolution goes through it. The row keeps the chain and contract it was
  created with as its **home Deployment**: the label it is shown under and the contract prices
  are asked for, so nothing that only reads a token changes. The migration is purely
  structural: each existing token row gains its home Deployment, and nothing is merged.
- Settling a token as a Deployment of another moves its contracts and its legs to the other and
  removes it. That is allowed only while every leg it has is an unclassified inflow — which mints
  no lot — and no Stance, price-relevant record or corporate action names it.
- A native coin keeps keying on its symbol, so ETH paying gas on a rollup is the same Instrument
  as on Ethereum. Its chain is its home chain, a label; the wallet Account says where it is held.
- Network facts are recorded on new transfers. A re-read that matches an existing record by its
  external identifier fills facts it lacks and never overwrites one.
- Lots stay per Account per Instrument. A wallet's chain decides which Deployment it holds, so
  FIFO never needs the chain.
- Settling an impostor no longer competes with the real token on a chain where it has no
  Deployment, and a transaction hash stated on both sides can prove a self-transfer.
