---
context: open-leprechaun
---

# Open Leprechaun — Domain Glossary

A self-hosted ledger of everything the Admin owns — crypto on exchanges, crypto in self-custody,
futures positions, and shares, ETFs and funds at brokers — that knows German tax law well enough
to produce the figures for a tax return and shows its working for every one of them.

This is the ubiquitous language. Code identifiers, API fields, UI copy and issue titles use these
terms unchanged, and honour every _Avoid_ line. Terms are kept in their long form where the
nuance is load-bearing; a two-sentence definition of **Stance** would have lost the reason it
exists.

## Places and holdings

### Platform

Any place that holds value, distinguished by its `kind`: `exchange`, `cold_storage`,
`software_wallet`, `broker`, `bank`.

A broker Platform carries the **withholding** behaviour that decides whether income arrives
already taxed at source. It lives here, on the Platform, because it is a fact about the
institution rather than about any one holding — with a per-**Account** override for the case where
one brand operates through several entities with different tax status.

A Platform may be removed only while it holds no **Account** and no **Connection**. One that has
either stays: removing a Platform never takes anything else with it.

_Avoid_: "Exchange" used generically. It means only `kind = exchange`; used as the name for
anything that holds value it asserts "trading venue" for things that are not one.

### Account

One holding under a **Platform**, and the boundary for FIFO lot matching — per Account per
**Instrument**.

An Account is scoped as finely as its Platform can **evidence**, because the scope of an Account
is the scope of FIFO. A device that names each account and its extended public key on every
exported row yields one Account per named account; a device whose export names only an address
yields one Account per device and chain. Mixed granularity across Platforms is correct rather than
untidy — a boundary can only be drawn where the evidence supports it.

An Account records an address, IBAN or reference as metadata only, never as a data source, and may
record extra software required to reach it.

An Account may be removed only while nothing was ever recorded in it and no **Connection** is
paired with it. What the Admin declared about it — a **Stance**, a withholding override — goes
with it; history never does, so an Account that has any stays for good.

_Avoid_: "Wallet" for a brokerage account.
_Avoid_: "account" for the credentialed link to a venue — that is a **Connection**.
_Avoid_: "account" for the reference a venue prints on a statement — that is an external reference
held by the Account.

### Position

One **Instrument** held at one **Account**: the quantity the ledger's legs sum to, its cost basis
read from the **Tax Lots**, and a current value stated only where something can vouch for one.
A Position standing ignored, dangerous or unacknowledged — or one nothing can price — stays
visible wearing an explicit marker and stands outside every total: never hidden, never counted
as zero. Cash is a Position like any other, the numéraire valued by identity.

_Avoid_: "Position" bare for the normalized ingestion row or for a futures **Derived Position** —
those belong to ingestion and derivatives vocabulary.

### Portfolio Snapshot

What the portfolio measured on one day, stored: the value of every counted **Position** beside the
cumulative **contributions** and **withdrawals** of the ledger as it stood then. One per
Europe/Berlin date — a later measurement of the same day replaces the earlier — taken by a
**Scheduled Task**. An observation, never a derivation: a ledger corrected afterwards changes the
next snapshot, not an earlier one.

_Avoid_: "snapshot" bare for this where a **Normalized Position** could be meant — that one is what
a venue says is held, and feeds only **Reconciliation**.

### Contribution · Withdrawal

Value that crossed the ledger's edge. A **contribution** arrived from outside: a transfer in that
no confirmed self-transfer explains, or an **Opening Balance**. A **withdrawal** left for outside: a
transfer out nothing matches, or a spend. Each is valued as of its own day; an Opening Balance at
its declared estimate. Together they are the ledger's **flows**; one nothing stored can value is an
**unvalued flow**, counted beside the sums it stands outside. Value less contributions plus
withdrawals is the **result** — everything the holdings did, realised or not.

_Avoid_: counting income as a contribution — a dividend or a staking reward is what the holdings
earned, not money put in.
_Avoid_: "deposit" as a transaction type. There is none; a deposit is a transfer in that nothing
inside the ledger sent.

### Custody Type

Where the assets of an **Account** actually sit, judged from its Platform's kind: `cold_storage`
and `software_wallet` are **self-custody**, `exchange`, `broker` and `bank` are **third-party
custody**. A grouping vocabulary for presentation — never a tax input.

### Depot

The domain word for an **Account** under a broker **Platform** — one that holds securities and
cash. It is vocabulary, not a schema entity: there is no Depot table, no Depot subtype, and
nothing branches on it. It appears in UI copy because it is what the Admin and the broker both
call the thing.

A Depot may hold coins beside its securities. Nothing about the Account says how a position is
taxed: the regime follows the **Instrument** — a coin's sale is a private sale, a security's is
capital income — whichever Account holds it.

### Connection

The single credentialed link to one venue account: one key and secret, plus a passphrase where a
venue requires one, entered once and managed in settings. A Connection powers every adapter kind
that venue supports, which are tested and synced together with results and failures reported per
kind. Several Connections to the same Platform are allowed.

_Avoid_: "credential" for the whole thing — that is only the secret material, one ingredient.
_Avoid_: "source" for the Connection itself; source is the per-kind provenance string an adapter
stamps on imported rows.

## Instruments

### Instrument

The unifying concept over crypto assets, securities and cash, distinguished by `family`.

A crypto Instrument with a contract is keyed on **chain and contract address**; a native coin keys
on its symbol, because for a native coin the symbol *is* the identity. A symbol is otherwise a
display label and a resolution hint, never authoritative.

Securities key on **ISIN**, with an identifier history so that a lot acquired under a superseded
identifier survives a merger or redomiciliation. WKN and ticker are lookup aliases only.

_Avoid_: keying anything on a symbol alone. Two unrelated tokens can share a ticker, and keyed
that way they collapse into one row where the loser inherits the winner's price, name and logo.

### Listing

One place an **Instrument** trades: a venue plus the currency it is quoted in. The same ISIN lists
on several venues in several currencies, so a price source points at a Listing rather than at the
Instrument — otherwise a quote carries no statement about which market or which currency produced
it.

### Cash

Fiat money, modelled as an **Instrument** (`family: cash`) like any other — not as a bare balance
attached to an Account. A euro, a dollar and a **Stablecoin** are all Wirtschaftsgüter under
German law, and giving them one shape means one holdings query, one lot engine and one
reconciliation rather than three.

**EUR is the numéraire**: the currency every taxable figure is expressed in, and moving it is
therefore not itself a disposal. Every other cash Instrument — a foreign-currency balance at a
broker no less than a stablecoin on an exchange — is an ordinary asset whose disposal is a private
sale with a **Haltefrist**.

_Avoid_: "cash balance" as a distinct kind of thing from a holding. It is a holding.
_Avoid_: treating EUR's exemption as a property of *cash*. It is a property of the numéraire;
another jurisdiction would exempt a different currency.

### Security

A share, ETF, fund, bond or certificate. Taxed as capital income: **no Haltefrist**, FIFO per
**Depot**, gains into a **Verlustverrechnungstopf**.

### Stablecoin

A Kryptowert like any other, not a cash equivalent. Spending one is a disposal — every exchange of
a Kryptowert for fiat, goods, services or another Kryptowert counts, explicitly including
stablecoin-to-stablecoin swaps. Gains are the currency drift over the holding period, usually
small but not nil.

Their EUR value comes from the **daily reference rate**, not a crypto price provider: provider
coverage of stablecoins is poor, and an unpriced disposal books zero proceeds against a real cost
basis, manufacturing a large phantom loss.

_Avoid_: treating them as an untracked "quote currency" — the balance then grows without bound and
a real disposal goes unrecorded.

### Stance

The Admin's standing position on an **Instrument**: `unacknowledged`, `kept`, `ignored`, or
`dangerous`. It is a stance, not a forensic verdict — it says what the Admin will do about the
thing, not what the thing provably is.

New Instruments arrive `unacknowledged`, and an inflow of one **mints no Tax Lot**. It is
recorded, so the ledger still reconciles against the wallet, and it waits in an inbox until the
Admin classifies it. The default is therefore deny rather than accept: the failure mode of an
unrecognised token is an item awaiting a decision, not a holding silently valued at zero.

`dangerous` applies to the Instrument globally — a token whose approval drains a wallet is
dangerous everywhere. `ignored` and `kept` apply per **Account**, which is what lets a genuine
holding bought at one venue coexist with dust of the same Instrument sprayed at another. Both stay
visible, because the holding genuinely exists on-chain, and neither can ever acquire a price
source — for `ignored` that means ignored wherever it appears, since the same coexistence that
motivates the per-Account scope requires a holding kept anywhere to stay priceable.

Materiality requires a **known price**. An inflow valued at zero because nothing prices the
Instrument is *unknown*, never immaterial, and must never be discarded on that basis.

Subsumes what would otherwise be two concepts — an untrusted asset and a de-minimis inflow —
both of which are needed only when Instruments are keyed on symbol.

_Avoid_: "scam token" — it asserts a claim that usually cannot be substantiated, and reads wrong
for a legitimate asset whose ticker was merely collided with.
_Avoid_: reading `unacknowledged` as a judgement. It means only that nobody has looked yet.

## The ledger

### Transaction

One economic event, recorded as a set of **legs** that balance: what left, what arrived, and what
a fee consumed. A share purchase is euro out and shares in; a crypto trade is one Instrument out
and another in; a dividend is cash in against an income event. More than two legs are expressible,
so a fee paid in a third asset is not a special case.

A **fee attaches to the leg it was charged against**, and its tax treatment is read from that
leg's regime rather than from the transaction's type — which is what makes a currency-conversion
fee a cost of acquiring that currency rather than a transaction cost of the trade it enabled.

_Avoid_: "both legs" as though two were the maximum.

### Original Amount

What a trade settled in another currency than it was priced in states beside its legs: the amount
as priced, the currency it was priced in, the rate the broker applied and the date that rate is
of. The legs stay what moved through the **Depot** — the security and the cash actually debited or
credited — so the cash balance matches the broker's. The rate is the broker's own, kept so the
settled amount can show its working; no tax figure is computed from it.

_Avoid_: a foreign-currency leg for a currency the Depot never held — its disposal would be a
private sale that never happened.

### Windfall

What keeping an unsolicited inflow settles it as when it was received for **no
counter-performance** — the default answer. Not income: with no Leistung there is nothing under
§22, and per the BMF letter of 10.05.2022 no Anschaffungsvorgang either, so the holding stays
visible at zero basis while its later disposal falls outside §23. Received *for* a
counter-performance, the same inflow settles as an **airdrop** instead — §22 income at market
value on receipt.

_Avoid_: filing a Windfall under income "to be safe". The safety would invent §22 income the law
does not see.
_Avoid_: "airdrop" for both cases — in this vocabulary an airdrop is the one given for a Leistung.

### Tax Lot

A single acquisition that creates a fungible unit of cost basis, consumed by disposals FIFO within
its **Account** and **Instrument**.

Lots are a **materialisation, not a source of truth**. The Transaction ledger is the only truth;
lots and their consumptions are derived from it in full, from the beginning of time, and stored
only so that holdings and reports need not replay the ledger on every request. Each materialisation
records the fingerprint of the inputs that produced it, so a lot table that no longer matches the
ledger is detectable by the same mechanism that marks a report stale.

_Avoid_: reading a persisted lot as authoritative. It is authoritative only while its fingerprint
matches.

### Opening Balance

A position that already existed when the available history begins. It behaves like an inbound
transfer but declares that its **cost basis is reconstructed, not observed**; lots minted from one
are marked, and any disposal consuming such a lot is flagged, so a report can say which figures
rest on an assumption instead of presenting them with the confidence of a documented purchase.

Two cases, and the difference decides a tax outcome. Where the **acquisition date is known** and
only the basis is estimated, the date is used as given — because an exempt disposal's gain is
excluded entirely, so for a long-held position the date is load-bearing and the basis is cosmetic.
Where **both are reconstructed**, date it at the start of known history: that makes disposals
short-term rather than assuming an older, Haltefrist-exempt acquisition, which is the conservative
reading.

_Avoid_: recording one as a plain transfer with an explanatory note — the assumption then looks
identical to a real movement in every report.
_Avoid_: applying the conservative dating where the date is actually known. It manufactures tax on
holdings that are exempt.

### Corporate Action

An issuer event that changes a holding without a trade: split, reverse split, spin-off, merger,
capital return. A split rescales quantity and per-unit basis inversely, leaving total basis and
acquisition dates untouched, with no taxable event. A capital return reduces the cost basis of
open lots rather than booking income. Spin-offs and mergers are recorded and **flagged for manual
review**, because their treatment is fact-specific and the app must not assert one.

Because lots are derived, reversing a Corporate Action is the removal of the event followed by a
rebuild.

A reverse split is a split whose ratio falls below one — one kind, not two. An identifier change
that leaves the paper the same is not a Corporate Action: the **Instrument**'s identifier history
absorbs it and no lot moves.

_Avoid_: editing a lot to reflect one. The event is recorded; its effect is derived.

### Import Batch

One import, recorded as a unit and reversible as a unit. Every import previews before it writes,
commits as a separate act, and deduplicates on source and external identifier so that re-importing
the same file changes nothing.

### Staking Delegation

Committing a holding to a validator to earn rewards. It is **not a disposal**: ownership never
changes, so it creates no private-sale event and leaves cost basis and the **Haltefrist**
untouched — the one-year period keeps running, and staking does not extend it to ten. Only the
resulting rewards are taxable, as **Sonstige Einkünfte** at market value on receipt.

What differs between chains is *location*, not tax. Some chains delegate by certificate and the
coins never move; others move them into a validator's pool, so the address on record no longer
holds them. Since ownership is unchanged, that move is a transfer between the Admin's own Accounts
rather than a disposal, and the acquisition date carries across.

Tracked as a marker per **Account** and **Instrument** — the same coin may be delegated in one
Account and idle in another, so neither the Instrument nor the Account alone can express it. The
marker is informational and describes the present, so removing it means "no longer delegated".

_Avoid_: treating a delegation as a transfer to nowhere — it would consume the lot and silently
destroy the holding period on coins that never left the Admin's control.
_Avoid_: a per-Instrument "is staked" flag — it cannot say *where*, which is the only part that
varies.

## Ingestion

### Exchange Adapter · Broker Adapter · CSV Connector · Address Indexer

The four shapes of ingestion, each a port with a fake. An **Exchange Adapter** and a **Broker
Adapter** authenticate against an account. A **CSV Connector** parses an exported file — a
wallet's export, or the statement of a broker that offers no API, which states the same records a
Broker Adapter pulls and lands the same way (ADR-0027). An
**Address Indexer** takes a chain and an address, requires no credentials, and is read-only by
nature rather than by permission — it is the mode for a self-custody wallet that publishes neither
an export nor an account, and the only one that sees unsolicited inflows as they arrive.

A port absorbs its venue's quirks — authentication and signing, pagination, rate limits, capped
lookback windows, symbol discovery, timezone and units — and emits only **Normalized** records. No
port touches the database, converts to EUR, or computes tax; core code never learns a venue's
name. Each declares its capabilities, including maximum lookback.

Exactly one ingestion mode is **authoritative per Account**. A second source may reconcile against
it but may not write. The adapter kinds of one **Connection** are one ingestion mode — the same
credentialed link to the same venue account — so those paired with one Account write into it
together, each under its own provenance. That is how a venue whose one account holds coins beside
securities is served: a kind of each port, both paired with the one **Depot**.

_Avoid_: "connector" for a credentialed adapter, or "adapter" for a file parser — the distinction
is which of the four shapes it is.
_Avoid_: integration, client, importer.

### Normalized Trade · Transfer · Fill · Funding · Security Trade · Dividend · Position · Cash Movement

The canonical, venue-agnostic representations a port emits: the sole input contract between
ingestion and core. Each carries its venue's external identifier, which together with the source
forms the deduplication key. A **Normalized Fill** carries optional enrichment — position side,
reduce-only, per-fill realised result — populated by venues that expose it, making derivation
exact, and left unset otherwise.

A **Normalized Position** is a snapshot of what the venue says is held, never history: it travels
apart from every record that lands in the ledger and has exactly one consumer, **Reconciliation**.
A broker states a security's position by its ISIN; the symbol beside it is only a label.

A **Broker Adapter**'s records name a security by its ISIN — the ledger's own identity for it — so
a paper the ledger has never seen arrives flagged for review instead of refusing the sync. A
statement that names a paper by its ticker alone states a resolution hint: exactly one security
in the ledger may answer to it, and nothing is minted from it. What a
broker's history states that is no transaction — a split, a return of capital — is **passed over
by name**: reported for the Admin to record, never landed and never dropped.

An **Address Indexer**'s Normalized Transfer names what moved by the chain's own identity — its
coin, or a token's contract — never by a bare symbol, which is what lets an Instrument the ledger
has never seen arrive `unacknowledged` instead of refusing the read. A network fee the address paid
for a transaction that moved nothing else is its own record, a **Normalized Network Fee**.

### Reconciliation

The comparison, per **Connection** and per **Instrument**, of the live balance a venue states
against the tracked balance the **Transactions** account for. The difference is live less tracked,
and one beyond the configured tolerance is a **gap**.

A gap is reported and never filled: a snapshot can say that something is missing, but not what it
cost or when it arrived, so closing one from it would invent a cost basis. The Admin closes a gap
deliberately, by one of two honest resolutions — importing the history that explains it, or
recording an **Opening Balance**, which declares its own uncertainty. An Opening Balance only ever
adds a position, so it is offered where the venue holds more than is accounted for, never to
explain quantity away.

Reconciliation writes nothing to the ledger, so it is not bound by the authoritative-source rule: a
source that may not write into an Account may still reconcile against it. What it does leave behind
is the record that it ran — when, and how many lines and adapter kinds it left open — per
Connection, replaced by the next run.

_Avoid_: "sync" for reconciling — a sync lands records, a reconciliation only compares.
_Avoid_: adjusting, correcting or balancing entry — there is no transaction type that absorbs a gap.

## Market data

### Price Chain

The documented order of crypto price providers (CoinGecko, then DefiLlama), each behind one
port. A provider identifies an Instrument by the ledger's own identity attributes — chain and
contract for a token, symbol for a native coin — and maps them to whatever identifiers it uses;
an Instrument it cannot map falls through to the next provider. **No provider-specific
identifier being absent may exclude an Instrument from pricing.**

What a provider answers becomes the stored **last known price** — price in EUR, source, and the
instant the quote represents. When every provider fails or passes over an Instrument, the last
known price is served **clearly labelled stale** with its source and age; an Instrument nothing
has ever priced is named **unpriced**, never valued at zero. Staleness is reported by naming
the affected Instruments, and a provider's rate limit is its own named condition, distinct from
an outage.

The chain prices only what the **Reference Rate** universe cannot: a **Stablecoin** routes to
its peg's daily rate, and a `dangerous` or everywhere-`ignored` Instrument may never acquire a
price source.

_Avoid_: a symbol-keyed provider lookup for tokens — two tokens legitimately share a ticker,
and one would inherit the other's price. Only a native coin, whose symbol is its identity, maps
through its symbol.
_Avoid_: reading "stale" as an age judgement. It is an outcome — the chain could not answer
just now — not a threshold.

### Historical Price

The price that applied when an event happened: the stored **daily close** of the Instrument for
the UTC day of the event's instant, kept with the provider that answered. It — never the last
known price — values an event, so income and cost basis are real rather than backfilled from
today. An import resolves it on commit for every row that states no price of its own: a row
states its price when one whole side of an exchange is cash or a **Stablecoin** and the other
side is a single position; anything else only the **Price Chain** can answer — income, a spend,
a crypto-for-crypto trade, a bare movement, a fee paid in a coin — wants the close of its day.

A row the chain could not price is listed in the import result as **unpriced** and awaits a
valuation; the scheduled price update asks again for every event still awaiting a close, and a
backfill of the Instrument's closes settles it by hand. A provider's answer of zero is no
answer, and a day not yet over has no close.

_Avoid_: valuing a past event at the last known price.
_Avoid_: reading an unpriced inflow as worthless — it is unknown, never immaterial.

## Derivatives

### Fill

A single futures trade execution: a side with price, size and fee at a timestamp. Fills are the
immutable source of truth for imported futures activity; everything else is derived from the
ordered fill sequence per symbol.

_Avoid_: trade, execution. An order may produce several Fills.

### Derived Position

A futures position reconstructed from the full sequence of **Fills** for a symbol rather than
entered by hand, identified by its source. Manually entered and Derived Positions share one model
and one tax treatment; only their origin differs.

### Funding Fee

A periodic financing payment on a perpetual contract, pulled separately from **Fills** and
attributed to the position open for that symbol at the payment timestamp. Counts toward net
result. Unattributable funding is surfaced, never dropped.

### Inverse Contract

A futures contract that settles in the coin rather than a quote currency — coin-margined. Closing
one has two consequences, both recorded: the net result is capital income (a **Section 20 Event**
in the Termingeschäfte pot, converted at the close), and the same net puts the settlement asset
into the books — a **Tax Lot** minted at the close, at the coin's EUR value there, its
**Haltefrist** starting at the close. Its result cannot be derived by net accounting — a
quote-currency price difference is the wrong unit — so every **Fill** states the variant and an
inverse stream derives only from venue-stated per-fill results; a port that cannot tell either
refuses explicitly rather than converting wrongly.

_Avoid_: defaulting an unstated variant to linear. That is precisely the wrong conversion the
refusal exists to prevent.

## German tax

### Tax Year

The German calendar year a realisation is reported in, bounded by **Europe/Berlin** local time —
the year follows the event's *local* date, not its UTC date. A futures position counts in the year
it is **closed**; a spot sale or income event in the year it is **executed**; an open position in
no year. A trade in the first hour after New Year in German time therefore belongs to the new year
even though it is still 31 December in UTC. Timestamps are absolute instants; only their
interpretation into a year uses the local boundary.

### Reference Rate

The euro foreign exchange reference rate the ECB publishes each TARGET business day — the one
canonical source every foreign-currency amount converts to EUR by (ADR-0017). Conversion uses the
rate of the **event date** — the Europe/Berlin local date of the event's instant, the same clock
that bounds the **Tax Year** — never a rate of report time. A weekend or holiday resolves to the
most recent publication on or before the date, at most seven days back; beyond that the conversion
is an error naming the gap, never a silently stale figure. Rates are stored as published and never
overwritten, and the rate and its date travel with every converted amount, so a re-run reproduces
the same figure exactly. A **Stablecoin**'s EUR value comes from its pegged currency's reference
rate, not a crypto price provider.

_Avoid_: "exchange rate" from a market-data provider for anything a tax figure rests on — venue
rates vary by moment, are revised silently, and carry no citation.

### Haltefrist

The one-year holding period for spot crypto and other private assets. Assets held more than a year
are exempt on disposal. The period runs between absolute instants and is therefore unaffected by
timezone. A self-transfer does not restart it; a **Staking Delegation** neither restarts it nor
extends it to ten years.

**Securities have no Haltefrist** — holding period never exempts a securities gain.

### Freigrenze

An all-or-nothing annual exemption limit: if the relevant income stays *below* the limit the whole
amount is tax-free; once it reaches the limit the *full* amount is taxable, not just the excess.
Two instances apply — one for private sales, one for **Sonstige Einkünfte**, the latter phrased as
*weniger als*, so exactly the threshold is already fully taxable. Every limit is per-year
configuration with a cited source.

_Avoid_: confusing it with **Sparerpauschbetrag**, which is a deduction rather than a threshold.

### Sonstige Einkünfte (§22 Nr. 3 EStG)

Crypto income taxed as Leistungen at market value on receipt — staking rewards, lending interest,
non-commercial mining, and airdrops received for a Leistung — pooled under a single annual
**Freigrenze** and taxed at the recipient's personal marginal rate, never the **Abgeltungsteuer**
that applies to capital income. The report states the taxable amount, not a euro tax owed, since
the marginal rate is unknown.

_Avoid_: "staking income" for the whole bucket — it also holds interest, mining and airdrops.

### Section 20 Event

The single shape every source of capital income is reduced to before tax is computed: a date, a
**category**, a gross amount, a **Teilfreistellung** rate, the German tax already withheld at
source, any **Quellensteuer** with its source country, and a reference to the record that produced
it.

Futures closes, share disposals, fund disposals, dividends, distributions, interest and
**Vorabpauschale** all emit this one shape. The engine reads nothing else: per year it nets within
each category, applies that category's per-year loss cap, consumes and refreshes that category's
carryforward, sums what survives, applies the **Sparerpauschbetrag** once across the total, and
applies the rate.

The point of the shape is that no producer of capital income knows anything about allowances,
categories or rates — it emits events, and the engine alone decides.

_Avoid_: computing tax anywhere a Section 20 Event is produced.

### Verlustverrechnungstopf

The statutory bucket a capital-income loss may be offset within. Three: **Aktien** (share sales,
which offset share gains and nothing else), **Sonstige** (funds, bonds, certificates, interest,
dividends, **Vorabpauschale**), and **Termingeschäfte** (futures). A loss never crosses from one
pot to another, and an unused balance carries forward within its own pot into later years.

A pot's balance may also **open** with a carryforward established outside this application — a
loss assessed for a year that predates the ledger. That opening balance is configuration entered
from the assessment, not a figure the engine derives, and its absence means zero rather than
unknown.

_Avoid_: netting across pots at any point, including "just for the summary". The pots are the
reason the declared figure survives contact with the Finanzamt.

### Sparerpauschbetrag

The annual capital-income **deduction**, applied once across the combined total after loss
offsetting and never per source. Reduced first by any portion already consumed at source under a
**Freistellungsauftrag**, so the application can never claim more allowance than exists.

_Avoid_: applying it as a **Freigrenze**. It is a deduction, not an all-or-nothing threshold.

### Freistellungsauftrag

An exemption order lodged with a German broker, telling it to let income through untaxed until an
allocated slice of the **Sparerpauschbetrag** is used up. Recorded per withholding **Platform**;
absent means none. It matters because income that already passed untaxed at source has consumed
allowance the engine must not grant again.

### Abgeltungsteuer

The flat rate on capital income: the base rate plus solidarity surcharge, rising where church tax
is elected — computed by the exact formula including church tax's own deduction effect, not by an
approximation. All components are per-year configuration.

### Teilfreistellung

The portion of a fund's gains and distributions exempted to compensate for tax levied at fund
level. Applies to distributions, **Vorabpauschale** and sale gains alike, at a rate that depends on
the fund's category. Prefilled from a provider where available, always overridable, with the source
of the value shown. A fund with no classification blocks report finalisation rather than silently
assuming none.

_Avoid_: treating it as a deduction from tax — it exempts a share of the *income*.

### Vorabpauschale

The annual advance lump sum on an accumulating fund that distributed less than a notional minimum
return. The base yield is the start-of-year value times the **Basiszins** times the statutory
factor; the amount is that yield less the year's distributions, floored at zero, then capped at the
year's increase in redemption value. In the year of acquisition that amount — not the base yield
before the cap — goes down by one twelfth for each full month preceding the month of acquisition,
which makes it a figure of the Tax Lot. Zero when the fund fell in value, and none at all for a
fund not held at the accrual moment. It applies to every fund, distributing ones included, wherever
the distributions fall short of the base yield.

Its inputs are entered, never derived: the Basiszins and the factor per year, and per fund and year
the first and last redemption price and the distributions per unit, in EUR, each with its source.

It accrues on the first banking day of the **following** year and is therefore declared in that
year — the year it derives from and the year it is declared in are distinct and must both be named.
It is reduced by **Teilfreistellung**, enters the *Sonstige* pot, and is tracked per lot and
deducted from the gain on eventual sale so the same amount is never taxed twice.

_Avoid_: calling it a tax — it is an amount of income deemed to have accrued.
_Avoid_: substituting a market close for the fund's redemption value. The app refuses to compute
rather than approximate.

### Basiszins

The base rate published annually that drives the **Vorabpauschale**. Per-year configuration taken
from the published source, never a constant in code; a year with no Basiszins set cannot be
computed.

### Quellensteuer

Foreign withholding tax on a dividend. Creditable against German tax up to the treaty limit;
anything above is reclaimable from the source country, which this application reports but does not
pursue. Recorded per dividend with its source country, because creditability depends on which
country withheld.

The ledger's in-leg of a dividend is the **net** that arrived; what was taken out before it did —
Quellensteuer, and the components of **Kapitalertragsteuer at source** — is declared on the
Transaction beside the security that paid, each amount in the received leg's own currency. The
**gross** is their sum, and it is the gross that becomes the **Section 20 Event**.

### Treaty limit

The share of a gross dividend a double-taxation treaty lets the source country keep — the ceiling
up to which its **Quellensteuer** is creditable, judged per dividend on that dividend's own gross.
Configuration per source country with a cited treaty article, never a constant in logic; a country
that withheld with no limit entered refuses to compute rather than crediting everything or nothing.

_Avoid_: "withholding rate" — that is what the source country actually took, which may exceed the
limit; the difference is the reclaimable part.

### Kapitalertragsteuer at source

Tax a German broker withholds and remits on the Admin's behalf. It distinguishes a withholding
**Depot**, where income is largely settled already, from a foreign one, where everything must be
declared. The report shows amounts settled at source separately from amounts still to declare.

### Form line

Where one of the report's figures goes on the return: the form — Anlage SO, Anlage KAP, Anlage
KAP-INV — and its Zeile, with the label printed beside it. A figure's mapping is **unambiguous**
when exactly one line of that year's form asks for it, **ambiguous** when the form offers several
and the ledger holds no fact that decides between them, and **unmapped** when no line numbers are
recorded for the year. Line numbers move between years, so each **Tax Year** has its own table
read from that year's official form; a year without one names the form and the field and says the
number is missing.

_Avoid_: carrying a line number from one year's form to another's, and guessing a line where the
form asks for a fact the ledger does not hold.

## Automation

### Scheduled Task

Work the application repeats on its own — a price update, a **Connection** sync, a **Portfolio
Snapshot** — on a schedule
the Admin controls: a cron expression read on the Europe/Berlin clock, and an enabled flag, per
task. The tasks themselves are declared in code; the Admin chooses when each runs, never what
exists. **Run-now** runs one immediately, whatever its schedule says and whether or not it is
enabled.

A task never overlaps itself: a second run — manual or scheduled — is refused while one is in
flight, not queued behind it. Each task states its last run alone — when it started, how long it
took, whether it succeeded, and the sentence saying what failed. A run the process did not survive
reads as failed, never as still running.

A missed fire is answered once, not once per fire missed, and a schedule counts forward from when
it was last chosen: enabling a long-idle task waits for its next due time.

_Avoid_: "job" or "cron job" — the unit is the task; cron is only how its schedule is written.
_Avoid_: "sync" for a task run in general — a sync is what one particular task does.

### Provider Condition

What asking a data provider last came to: `rate_limited` or `outage`, never conflated — one asks
for patience, the other for a look — and over as soon as the provider answers again. Recorded by
whatever asked, beside the provider's last answer and last failure, so the health panel reads it
without asking anyone. A failing provider **affects** the Instruments the latest price refresh
left without a fresh price while it was failing — named one by one; one that another provider
answered for affects nothing.

_Avoid_: "outage" for the application, or for prices as a whole — one provider failing is that
provider's condition and the staleness of the Instruments it names.

### First-Run Checklist

The walk from an empty database to a first tax report: set a password, enable two-factor, add
**Platforms** and **Accounts**, connect or import, reconcile, resolve blockers, generate a report.
Each step is **derived** on every read from what the database holds — an **Admin**, an Account, a
**Connection** or history, a recorded **Reconciliation** that left nothing open, a **Tax Year** with
activity and no blockers, a report — so a step reads done because the thing exists and open again
once it no longer does. A step is **optional** where the walk can finish without it: two-factor is
opt-in, and a ledger no Connection states a venue balance for has nothing to reconcile against.

_Avoid_: "dismiss", "skip" or "mark as done" — nothing about the checklist is stored, so there is
nothing to tick.
_Avoid_: "onboarding wizard" — it does not lead through screens; it states what exists and links
to where the rest is done.

## Presentation and access

### Admin

The single person who owns this instance and everything in it. There is exactly one, enforced at
the database, and there are no roles — every authenticated request is the Admin's.

_Avoid_: "User", which implies a directory of them.
_Avoid_: "account" for the Admin's identity or its settings — that word belongs to a holding under
a **Platform**. The Admin's credentials live under **Security**.

### Session

One live authentication of the **Admin**, held as a token digest with a sliding expiry. Several may
exist at once — one per browser or client that logged in — and each can be revoked independently.

_Avoid_: "login" for the thing that persists; a login is the act, a Session is what it leaves
behind.

### DisplayCurrency

The selected display currency. German tax calculations always use EUR regardless — DisplayCurrency
affects presentation only, and never a tax figure.

### Aggregate

One summary line over many tiny records of one origin, whose constituents remain retrievable in
full. Two kinds: a **bot** summarises a fill source's futures activity — a scope, not a member
list, because **Derived Positions** are rebuilt wholesale and only the scope survives — and a
**dust sweep** collects the trades that disposed many dust balances into one received
**Instrument**.

An Aggregate is presentation only. Its figures are sums over its constituents, never
recomputations, so summarising cannot change a number; the tax engines never read it — every
constituent position still emits its own **Section 20 Event** and every constituent disposal still
consumes its own **Tax Lots** — and membership sits outside the input fingerprint like a note, so
recording one marks no report stale. Disbanding one releases its members and touches nothing else.

_Avoid_: netting constituents into one synthetic record. The constituents are the record; the
Aggregate only collapses how they are shown.
_Avoid_: "dust sweep" for an unsolicited dust *inflow* — that is a **Stance** question.

### Bearer Token Auth

The token-in-the-response-body half of authentication, alongside the httpOnly cookie the browser
receives. One login endpoint serves both; the auth dependency accepts the cookie first, then the
bearer header.

### Two-Factor Authentication

An optional second login factor for the single Admin: a TOTP code required alongside the password
wherever authentication is active. Opt-in, with a verify-before-activate step at enrollment, and
nudged by a persistent reminder in production while it is off. Login stays one endpoint that
returns a distinct "code required" result, then issues the unchanged token once both factors pass.
A code is accepted once, and while the factor is active every change to a credential — the
password, or the factor itself — takes a current code as well. Activating it ends every other
**Session**. Deliberately has **no recovery codes** — the only anti-lockout path is a server-side
disable, which the UI states at enrollment.

_Avoid_: "two-factor authorization" — authentication proves *who* you are; authorization is *what*
you may do once authenticated.
