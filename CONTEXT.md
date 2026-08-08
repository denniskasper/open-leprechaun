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

_Avoid_: "Wallet" for a brokerage account.
_Avoid_: "account" for the credentialed link to a venue — that is a **Connection**.
_Avoid_: "account" for the reference a venue prints on a statement — that is an external reference
held by the Account.

### Depot

The domain word for an **Account** under a broker **Platform** — one that holds securities and
cash. It is vocabulary, not a schema entity: there is no Depot table, no Depot subtype, and
nothing branches on it. It appears in UI copy because it is what the Admin and the broker both
call the thing.

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
source.

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
Adapter** authenticate against an account. A **CSV Connector** parses an exported file. An
**Address Indexer** takes a chain and an address, requires no credentials, and is read-only by
nature rather than by permission — it is the mode for a self-custody wallet that publishes neither
an export nor an account, and the only one that sees unsolicited inflows as they arrive.

A port absorbs its venue's quirks — authentication and signing, pagination, rate limits, capped
lookback windows, symbol discovery, timezone and units — and emits only **Normalized** records. No
port touches the database, converts to EUR, or computes tax; core code never learns a venue's
name. Each declares its capabilities, including maximum lookback.

Exactly one ingestion mode is **authoritative per Account**. A second source may reconcile against
it but may not write.

_Avoid_: "connector" for a credentialed adapter, or "adapter" for a file parser — the distinction
is which of the four shapes it is.
_Avoid_: integration, client, importer.

### Normalized Trade · Transfer · Fill · Funding · Security Trade · Dividend · Position · Cash Movement

The canonical, venue-agnostic representations a port emits: the sole input contract between
ingestion and core. Each carries its venue's external identifier, which together with the source
forms the deduplication key. A **Normalized Fill** carries optional enrichment — position side,
reduce-only, per-fill realised result — populated by venues that expose it, making derivation
exact, and left unset otherwise.

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

## German tax

### Tax Year

The German calendar year a realisation is reported in, bounded by **Europe/Berlin** local time —
the year follows the event's *local* date, not its UTC date. A futures position counts in the year
it is **closed**; a spot sale or income event in the year it is **executed**; an open position in
no year. A trade in the first hour after New Year in German time therefore belongs to the new year
even though it is still 31 December in UTC. Timestamps are absolute instants; only their
interpretation into a year uses the local boundary.

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
factor, prorated by month of acquisition; the amount is that yield less the year's distributions,
floored at zero, then capped at the year's increase in redemption value. Zero when the fund fell in
value, and none at all for a fund not held at the accrual moment.

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

### Kapitalertragsteuer at source

Tax a German broker withholds and remits on the Admin's behalf. It distinguishes a withholding
**Depot**, where income is largely settled already, from a foreign one, where everything must be
declared. The report shows amounts settled at source separately from amounts still to declare.

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

### Bearer Token Auth

The token-in-the-response-body half of authentication, alongside the httpOnly cookie the browser
receives. One login endpoint serves both; the auth dependency accepts the cookie first, then the
bearer header.

### Two-Factor Authentication

An optional second login factor for the single Admin: a TOTP code required alongside the password
wherever authentication is active. Opt-in, with a verify-before-activate step at enrollment, and
nudged by a persistent reminder in production while it is off. Login stays one endpoint that
returns a distinct "code required" result, then issues the unchanged token once both factors pass.
Deliberately has **no recovery codes** — the only anti-lockout path is a server-side disable, which
the UI states at enrollment.

_Avoid_: "two-factor authorization" — authentication proves *who* you are; authorization is *what*
you may do once authenticated.
