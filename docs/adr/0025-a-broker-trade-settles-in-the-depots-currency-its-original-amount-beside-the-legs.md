# A broker trade settles in the Depot's currency; its original amount stands beside the legs

## Status

accepted

## Context

A broker is a different shape of source than an exchange (ADR-0008). It names a security by its
ISIN, which is the ledger's own identity for it (ADR-0010), where an exchange can only offer a
symbol. And it settles every trade in the Depot's currency whatever the security is priced in: a
euro Depot buying a dollar share is debited euros at the broker's own rate, plus a conversion fee.
The Depot never holds a dollar.

The ledger needs cash balances that match the broker's. The Admin needs to see the trade as it was
priced, and the rate that turned one figure into the other.

## Decision

The **Broker Adapter** is its own port with its own Normalized records: a Normalized Security Trade
and a Normalized Dividend name a security by ISIN, so the import framework resolves it or mints it
flagged for review — a broker sync never refuses over a paper the ledger has not seen.

The legs of a broker trade are what moved through the Depot (ADR-0011): the security, and the cash
the broker actually debited or credited for it, in the currency it settled in. The trade as it was
priced is a **declaration on the Transaction**, stored beside the legs like a dividend's withholding
(ADR-0022) — the **Original Amount**: the amount, the currency it was priced in, the rate the
broker applied (units of that currency per one unit of the settled currency, the way reference
rates are stated) and the date that rate is of. It is the broker's own rate, kept so the settled
amount can show its working, and no tax figure is computed from it.

Each fee is its own leg, attached to the leg it was charged against: a commission, stamp duty or
transaction tax to the security, a currency-conversion fee to the cash. The adapter says which, and
the fee inherits that leg's regime.

An event the broker's history states that is no transaction — a split, a spin-off, a return of
capital — is **passed over by name**: reported with the sync for the Admin to record as the
Corporate Action it is, never landed and never silently dropped.

Both account-authenticating ports hang off the same Connection (ADR-0004) and the same venue
registry. The sync service routes by what a kind pulled, never by which venue it is.

## Considered Options

- **Foreign-currency legs with a conversion Transaction.** Rejected: an out-leg of foreign cash is
  a disposal consuming a lot (ADR-0011), so every foreign trade would mint and at once dispose of
  currency the Depot never held, inventing §23 events and movements the broker's statement does not
  show.
- **Convert the original amount by the reference rate and book that.** Rejected: the cash balance
  would drift from the broker's by the spread on every trade. The reference rate (ADR-0017) values
  what the ledger holds in a foreign currency; here it holds none.
- **One port for exchanges and brokers.** Rejected, as ADR-0008 already did: a symbol-keyed record
  cannot carry an ISIN's certainty, and an ISIN-keyed one has nothing to say about a token.
- **Refuse the sync on a split.** Rejected: one split would bar a Depot from syncing for good, and
  the event has a home of its own outside the import.

## Consequences

- Cash at a Depot reconciles to the broker with no special case, and a second broker needs an
  adapter and a registry entry, nothing more.
- A dividend's gross is only as complete as what the broker states: where it states the gross but
  not what was withheld or by whom, the gross is kept on the event and the withholding stays the
  Admin's to declare.
- The Original Amount is informational. Editing a trade by hand leaves it standing as what the
  broker said.
