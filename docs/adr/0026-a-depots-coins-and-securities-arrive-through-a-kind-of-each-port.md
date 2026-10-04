# A Depot's coins and securities arrive through a kind of each port, as one ingestion mode

## Status

accepted

## Context

Some venues hold coins and securities in one account. The two account-authenticating ports cannot
each state the other's records, and deliberately so (ADR-0008, ADR-0025): the **Broker Adapter**
names a security by its ISIN, which is the ledger's identity for it, while an **Exchange Adapter**
can offer only a symbol for a coin, which the ledger must resolve and never mints from. A coin has
no ISIN, and a venue's API states neither its chain nor its contract.

The ledger, though, should hold what the venue holds: one **Depot**, with the coins and the
securities drawing on the same cash. Splitting it into a crypto Account and a securities Account
would invent a cash transfer for every purchase and break FIFO's Account boundary for no reason
the venue gives.

Until now exactly one source could write into an Account, and every adapter kind is its own source
("<venue>:<kind>") — so two kinds of one Connection could not share an Account.

## Decision

A venue whose one account holds both ships **a kind of each port** through its one Connection
(ADR-0004): a spot kind on the exchange port for the coins, a securities kind on the broker port
for the securities, the cash and the income. Neither port changes. Which kind states a movement
follows from the asset the venue names, never from anything about the account.

**The adapter kinds of one Connection are one ingestion mode.** They are the same credentialed
link to the same venue account, so the kinds paired with one Account write into it together. Each
keeps its own provenance string, its own deduplication registry and its own recorded result. The
Account's declared authoritative source stays whichever of them committed first; a commit is
admitted when the declaration is the committing kind's own source or that of a kind of the same
Connection paired with the same Account. Any other source — another venue, a file, an address —
is refused as before. A source string names a venue and a kind, never the Connection, so two
Connections to one venue are told apart no better than they were: the same kind of a second
Connection could always write where the first had, and now so can its sibling kind.

**One kind states the Depot's Normalized Positions.** Reconciliation compares a kind's snapshot against
everything its paired Account tracks, so two kinds each stating a part would each report the
other's holdings as gaps. The securities kind states the whole Depot — securities by ISIN, coins
and cash by symbol — and the spot kind states none.

**What neither port can express is passed over by the broker kind**, which alone has the means to
name it: a metal, an index, a reward paid in a coin, a tax withheld with no word on who withheld
it.

Nothing in the tax engines changes, and nothing reads the Account's or the Platform's kind to pick
a regime: a leg's regime follows its Instrument's family (ADR-0011), so a coin sold out of a Depot
is a private sale and a share sold beside it is capital income.

## Considered Options

- **One kind on an extended broker port, naming a coin by symbol.** Rejected: it gives the broker
  port a second identity scheme, the weaker one, and makes every broker adapter's consumer handle
  a record that may or may not resolve.
- **Two Accounts, one per kind.** Rejected: the venue has one cash balance, and FIFO's boundary is
  the Account as the Platform evidences it.
- **Any source of the same venue shares an Account.** Rejected: two Connections are two venue
  accounts, and one writing into the other's Account is exactly what the rule exists to refuse.

## Consequences

- An exchange venue's kinds may now share an Account too, where their records go through the
  import framework.
- A reward in a coin is not landed by a sync: the exchange port has no record for income, so it is
  passed over by name and shows as a Reconciliation gap until the Admin records it.
- The spot kind refuses its pull while a coin it names answers to no Instrument, as every exchange
  kind does; the securities kind lands regardless.
