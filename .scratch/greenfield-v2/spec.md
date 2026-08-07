# Open Leprechaun v2 — Greenfield Rebuild

Status: ready-for-agent

## Problem Statement

The Admin self-hosts a ledger of everything they own and needs German tax figures out of it
once a year. The existing implementation (v1) produces correct §23 / §22 / §20-futures numbers
for crypto, but three things about it now block the work rather than support it.

**The model lies in two places.** The top-level entity that holds value is called `Exchange`,
and roughly half its rows are hardware wallets — the name asserts "trading venue" for things
that are not one, and leaves no room for a broker at all. Below it, an `Asset` is keyed on its
**symbol**, which two unrelated tokens can share; the loser of that collision silently inherits
the winner's price, name and logo. An entire concept (`Untrusted Asset`) exists to work around
that one schema decision.

**The ledger cannot express money.** A transaction carries one asset, one quantity, and a
scalar EUR total. There is no currency column anywhere, no cash instrument, and no FX rate. So
a foreign-currency trade cannot be recorded, a cash balance cannot be held, and the other side
of a trade exists only as a second row that convention — not structure — keeps in step.

**§20 was built as "futures".** The annual summary carries flat futures-shaped totals. There is
no category, no statutory loss pot, and no carryforward between years. Capital income from
shares, funds, dividends, interest or **Vorabpauschale** has nowhere to go, and the allowance is
applied to a single source rather than to the combined picture the law actually taxes.

Meanwhile the Admin now holds securities as well as crypto, across brokers with different
withholding behaviour, and needs one set of figures covering both.

## Solution

Rebuild in a new repository, carrying over the domain knowledge and discarding the accreted
structure. Four changes carry most of the weight:

1. **Name the concepts honestly.** A **Platform** is any place that holds value; an **Account**
   is one holding under it and the boundary for FIFO; a **Depot** is what an Account under a
   broker is called. Crypto **Instruments** key on chain and contract, securities on ISIN with a
   **Listing** and an identifier history.

2. **Make the ledger balance.** **Cash** is an **Instrument** like any other, with EUR as the
   numéraire. Every **Transaction** is a set of legs that balance — what left, what arrived,
   what a fee consumed. Foreign-currency positions, cash balances and both sides of a trade all
   become ordinary cases rather than special ones.

3. **One §20 engine.** Every source of capital income reduces to a single **Section 20 Event**
   carrying a category. The engine nets within statutory **Verlustverrechnungstöpfe**, applies
   per-year loss caps, carries unused losses forward inside their own pot, and applies the
   **Sparerpauschbetrag** once across the combined total.

4. **Default to deny for things that arrive unasked.** An Instrument the Admin has never
   classified carries a **Stance** of `unacknowledged`, and an inflow of one mints no **Tax
   Lot** until it is classified. This replaces both `Untrusted Asset` and `De-minimis Inflow`.

The first deliverable is a correct German tax return for the 2026 tax year, covering crypto
spot, crypto income, futures and securities together.

## User Stories

### Foundations and operations

1. As the Admin, I want to bring the app and its database up from a clean checkout using
   documented commands, so that self-hosting does not require reverse-engineering the setup.
2. As the Admin, I want `pnpm` to be the single documented entry point for every task, so that
   I do not have to learn a second build system to run a migration.
3. As the Admin, I want Postgres to run in Docker while the API and web dev servers run on the
   host, so that I can attach a debugger to the code I am changing.
4. As the Admin, I want the API to serve its OpenAPI documentation, so that I can inspect the
   contract without reading the source.
5. As the Admin, I want `development`, `integration` and `production` to differ by a single
   environment variable, so that I can develop without login friction while deployments stay
   protected.
6. As the Admin, I want the UI to show an environment badge outside production and a version
   line identifying the running build, so that I always know which instance I am looking at.
7. As the Admin, I want every schema change to ship as a reviewed migration tested in both
   directions, so that upgrading a deployed instance never means editing the database by hand.
8. As a developer, I want an idempotent seed covering every asset class and regime, so that I
   can exercise portfolio, tax and reporting paths without touching real data.
9. As the Admin, I want CI to run checks and only then trigger the deployment, so that a red
   run never reaches production.
10. As the Admin, I want CI split into an orchestrating workflow plus one reusable workflow per
    concern, so that a change to the web pipeline does not require reading the API pipeline.
11. As the Admin, I want one page showing provider reachability, per-connection sync results,
    scheduler state and database size, so that I can tell whether the numbers I am looking at
    are fresh.
12. As the Admin, I want a failing provider named specifically along with the Instruments it
    affects, so that one outage is never reported as a total outage.

### Identity and security

13. As the Admin, I want a first-run screen that sets my password when no admin exists, so that
    a fresh deployment is never left open.
14. As the Admin, I want one login endpoint serving both web and any future client, so that
    session behaviour cannot drift between them.
15. As the Admin, I want to enable a TOTP second factor with a verify-before-activate step, so
    that a leaked password alone cannot open my financial history.
16. As the Admin, I want to be told at enrollment that there are no recovery codes and that the
    only anti-lockout path is a server-side disable, so that I am not surprised later.
17. As the Admin, I want a persistent reminder in production while two-factor is off, so that I
    do not leave it disabled by inattention.
18. As the Admin, I want every venue credential encrypted at rest and never returned by any
    endpoint, so that a database dump does not hand over my accounts.
19. As the Admin, I want each venue's required credential scope stated in the UI, so that I
    grant read-only access rather than more.

### Platforms, Accounts and custody

20. As the Admin, I want exchanges, self-custody wallets, brokers and banks to be one
    **Platform** concept distinguished by kind, so that every holding has a location and a new
    venue type needs no new hierarchy.
21. As the Admin, I want every **Account** to belong to exactly one Platform, so that no holding
    is locationless.
22. As the Admin, I want settings to group Platforms by kind, so that I can find a wallet
    without scrolling past every exchange.
23. As the Admin, I want each Account to be the boundary for FIFO lot matching, so that
    matching follows where the assets actually sat.
24. As the Admin, I want an Account scoped as finely as its Platform can evidence — per named
    account where the export names one, per chain where it does not — so that the FIFO boundary
    rests on evidence rather than convention.
25. As the Admin, I want an Account fed by a sync connection marked as managed and paired to
    that connection, so that I can see which holdings maintain themselves.
26. As the Admin, I want an Account to record an address, IBAN or reference as metadata only,
    so that identifying information never silently becomes a data source.
27. As the Admin, I want an Account to record extra software required to reach it, so that I am
    not left guessing how to access a holding months later.
28. As the Admin, I want holdings to show custody type, so that I can see what I actually
    control versus what a venue controls for me.
29. As the Admin, I want to register each brokerage account as a **Depot** under a broker
    Platform, so that securities have a location with the right tax semantics.
30. As the Admin, I want withholding behaviour recorded on the broker Platform with a
    per-Account override, so that the common case cannot drift and the unusual case is still
    expressible.
31. As the Admin, I want a Depot to be required to have its withholding behaviour set before it
    can hold a position, so that no income is classified against an unknown.

### Instruments

32. As the Admin, I want crypto assets and securities to share one **Instrument** abstraction
    with family-specific attributes, so that portfolio, pricing and reporting are written once.
33. As the Admin, I want crypto Instruments keyed on chain and contract where a contract exists,
    so that two tokens sharing a ticker can never collapse into one row.
34. As the Admin, I want a symbol treated as a display label and a resolution hint, never as
    identity, so that no Instrument can inherit another's price or logo.
35. As the Admin, I want securities keyed on ISIN, so that identity is unambiguous.
36. As the Admin, I want each Instrument to keep an identifier history, so that a lot acquired
    under a superseded ISIN survives a merger or redomiciliation.
37. As the Admin, I want a **Listing** — venue plus quote currency — modelled separately, so
    that a quote states which market and which currency produced it.
38. As the Admin, I want to add a security by searching ISIN, WKN, ticker or name and picking
    from provider results, so that I do not hand-type instrument metadata.
39. As the Admin, I want to create a security manually when the provider has no coverage, and
    have it marked **unpriced**, so that it is never valued at zero.
40. As the Admin, I want an imported position for an unknown identifier to auto-create the
    Instrument and flag it for review, so that a row is never silently dropped.
41. As the Admin, I want each fund to carry its **Teilfreistellung** category and distribution
    policy, so that the taxable portion of its gains and distributions is right.
42. As the Admin, I want a fund's Teilfreistellung prefilled from the provider where available,
    always overridable, with the source of the value shown, so that I know whether I set it or
    inherited it.
43. As the Admin, I want an unclassified fund to block report finalisation with a direct action
    to classify it, so that nothing silently assumes a zero exemption.
44. As the Admin, I want **Cash** modelled as an Instrument, so that a buy has something to
    spend and my portfolio total is not wrong by my whole cash position.
45. As the Admin, I want EUR treated as the numéraire whose movement is not itself a disposal,
    so that ordinary euro payments create no taxable event.
46. As the Admin, I want every non-EUR cash Instrument treated as an ordinary asset with a
    **Haltefrist**, so that a foreign-currency balance is taxed the way the law taxes it rather
    than noted as an unmodelled area.
47. As the Admin, I want an Instrument I have never classified to carry a **Stance** of
    `unacknowledged`, so that nothing unrecognised enters my cost basis by default.
48. As the Admin, I want an inflow of an unacknowledged Instrument recorded but minting no Tax
    Lot, so that the ledger still reconciles while the tax position waits for me.
49. As the Admin, I want an inbox of unacknowledged Instruments with `keep`, `ignore` and
    `dangerous` as the available stances, so that classifying junk is a deliberate act.
50. As the Admin, I want `dangerous` to apply to an Instrument everywhere and `ignore` to apply
    per Account, so that marking dusted junk in one wallet does not zero out the same asset
    where I actually bought it.
51. As the Admin, I want an ignored or dangerous position to stay visible with a clear warning
    rather than be hidden, so that I am not surprised by a holding that genuinely exists.
52. As the Admin, I want an ignored or dangerous Instrument barred from ever acquiring a price
    source, so that it cannot re-enter valuation by accident.
53. As the Admin, I want to be asked, at the moment I acknowledge an unsolicited inflow, whether
    it was received for a counter-performance, so that the income question is settled when I
    have the context rather than at report time.

### Ledger

54. As the Admin, I want every Transaction recorded as a set of balanced legs, so that the
    disposal of what I spent is never silently missing.
55. As the Admin, I want a fee recorded as its own leg, so that it is never counted twice or
    attached to the wrong side.
56. As the Admin, I want a fee's tax treatment read from the regime of the leg it was charged
    against, so that a currency-conversion fee, a trading fee and a futures fee each land where
    they belong without special cases.
57. As the Admin, I want a stablecoin treated as a tracked Instrument, so that spending one is
    recorded as the disposal it is.
58. As the Admin, I want a securities trade to record the security leg and the cash leg in the
    trade currency, so that the Depot's cash position stays true.
59. As the Admin, I want a transaction vocabulary that names what actually happened for both
    crypto and securities, so that tax classification follows from the record rather than a
    guess.
60. As the Admin, I want every transaction type's tax consequence documented in one place that
    the tax engine alone reads, so that a classification cannot drift between the ledger and the
    report.
61. As the Admin, I want an unclassified inflow never assumed to be a purchase, so that no cost
    basis is invented.
62. As the Admin, I want the app to propose candidate matches between my own withdrawal and
    deposit by asset, quantity within a fee tolerance, and time window, so that I do not hunt
    for them.
63. As the Admin, I want a confirmed self-transfer to carry the original cost basis and
    acquisition date across, so that moving my own assets does not reset the Haltefrist.
64. As the Admin, I want the same mechanic to apply to a securities transfer between my own
    Depots, so that lot identity and acquisition dates survive a Depotübertrag.
65. As the Admin, I want an unmatched transfer shown as unmatched, so that it is never quietly
    treated as a disposal.
66. As the Admin, I want a position that predates my available history recorded as an **Opening
    Balance** whose basis is marked estimated, so that no report presents a reconstruction with
    the confidence of a documented purchase.
67. As the Admin, I want an Opening Balance to distinguish *acquisition date known, basis
    estimated* from *both reconstructed*, so that a long-held position I can date is not
    reported as short-term merely because I lack its purchase price.
68. As the Admin, I want conservative dating applied only when the acquisition date is genuinely
    unknown, so that the rule protects me without manufacturing tax on exempt holdings.
69. As the Admin, I want every disposal consuming an estimated-basis lot flagged, and the total
    exposed to estimation stated in the report, so that I know which figures rest on an
    assumption.
70. As the Admin, I want splits and reverse splits to rescale quantity and per-unit basis of
    open lots without changing total basis or acquisition dates, so that share counts stay right
    with no taxable event.
71. As the Admin, I want a capital return to reduce the cost basis of open lots rather than book
    income, so that it is reported as what it is.
72. As the Admin, I want spin-offs and mergers recorded, split by a ratio I supply, and flagged
    for manual review, so that the app never asserts a fact-specific treatment.
73. As the Admin, I want every corporate action to show a before-and-after preview of affected
    lots and to be reversible, so that I can undo a mistake without editing lots by hand.
74. As the Admin, I want to create, edit and delete any transaction by hand, so that I can fix
    what an importer got wrong.
75. As the Admin, I want an edited or deleted imported row marked as manually overridden, so
    that a re-import does not silently revert my correction.
76. As the Admin, I want deleting a transaction a finalised report depends on to be blocked or
    to mark that report stale, so that a filed figure never changes underneath me.
77. As the Admin, I want bulk reassignment of Account and bulk re-typing of rows, so that fixing
    a systematic import error is not a hundred edits.

### Import

78. As the Admin, I want every import to show exactly what it will create before it creates
    anything, so that a bad file never has to be undone.
79. As the Admin, I want the preview to list rows to be created, rows skipped with reasons,
    Instruments to be auto-created, and warnings, so that I can judge the file before committing.
80. As the Admin, I want confirmation to be a separate call that writes nothing during preview,
    so that a cancelled import leaves no trace.
81. As the Admin, I want every import recorded as a batch and reversible as a unit, so that one
    mistake is one undo.
82. As the Admin, I want re-importing the same file to be idempotent and the preview to say how
    many rows would be duplicates, so that I can re-run an import safely.
83. As the Admin, I want each CSV connector to declare the file it expects and reject a
    mismatched file clearly, so that a wrong file is refused rather than mis-parsed.
84. As the Admin, I want each connector to declare and convert the timezone and units its venue
    exports in, so that a local-time or sub-unit export is never taken at face value.
85. As the Admin, I want a connector that cannot support a variant to refuse it explicitly, so
    that it never converts something wrongly.
86. As the Admin, I want to map an arbitrary CSV's columns to ledger fields with a live preview,
    so that an unsupported venue does not block me.
87. As the Admin, I want a column mapping saved, named and reusable, so that a recurring export
    is a one-click import.
88. As the Admin, I want to import a broker's transaction export including buys, sells,
    dividends, distributions, fees and cash movements, so that securities history arrives
    without hand entry.
89. As the Admin, I want German tax withheld at source recorded per event, so that the report
    can distinguish what is settled from what I still must declare.
90. As the Admin, I want foreign withholding tax recorded per dividend with its source country,
    so that creditability can be assessed.
91. As the Admin, I want a foreign-currency trade to store the original amount and currency
    alongside the EUR amount with the rate and rate date used, so that the conversion is
    reproducible.
92. As the Admin, I want an imported row without a price to be given the historical price at its
    timestamp, so that cost basis is real rather than backfilled from today.
93. As the Admin, I want a row whose price cannot be resolved flagged rather than defaulted to
    zero, so that a gap is visible instead of wrong.

### Sync

94. As the Admin, I want one credentialed **Connection** per venue account powering every
    adapter that venue supports, so that I enter a key once.
95. As the Admin, I want testing and syncing to report results per adapter kind, so that one
    kind failing does not hide another succeeding.
96. As the Admin, I want venue specifics confined behind an adapter port emitting canonical
    normalized records, so that core code never learns a venue's name.
97. As the Admin, I want adding a venue to mean adding one adapter and a registry entry, so that
    no service, router or screen changes.
98. As the Admin, I want an **Address Indexer** port that takes a chain and address and returns
    normalized transfers, so that a self-custody wallet with no export and no account can still
    be tracked.
99. As the Admin, I want exactly one authoritative ingestion mode declared per Account, so that
    two sources covering the same holding cannot both write and double-count it.
100. As the Admin, I want a second source able to reconcile against an Account without writing to
     it, so that a cross-check costs me nothing.
101. As the Admin, I want broker positions and transactions pulled automatically where an API
     exists, so that securities keep up to date like crypto does.
102. As the Admin, I want the UI to state whether a broker is served by sync, import or manual
     entry, so that I know what maintaining it requires.
103. As the Admin, I want synced positions used for reconciliation only, never as a substitute
     for transactions, so that a position snapshot never becomes a phantom cost basis.
104. As the Admin, I want reconciliation to report live balance, tracked balance and the
     difference per Instrument within a configurable tolerance, so that missing history surfaces.
105. As the Admin, I want a reconciliation gap reported and never auto-filled, so that the app
     does not invent a cost basis.
106. As the Admin, I want each gap to offer the two honest resolutions — import the missing
     history, or record an Opening Balance with its uncertainty marked — so that I close it
     deliberately.
107. As the Admin, I want reconciliation to work for crypto balances and for securities and cash
     at a Depot, so that no asset class is exempt from the check.
108. As the Admin, I want each adapter to declare its maximum lookback and each sync to state the
     period it actually covered, so that I never mistake "no trades found" for "no trades exist".
109. As the Admin, I want a warning when a venue's coverage starts later than my earliest
     recorded activity elsewhere, so that a silent history gap is surfaced.

### Prices, FX and valuation

110. As the Admin, I want crypto prices sourced from a primary provider with a documented
     fallback chain, so that an asset the primary does not list still gets valued.
111. As the Admin, I want no provider-specific field being empty to exclude an Instrument from
     pricing, so that coverage does not depend on one vendor's identifiers.
112. As the Admin, I want the last known price stored with its source and timestamp and served as
     clearly labelled **stale** when every provider fails, so that I am never shown a stale
     figure as current.
113. As the Admin, I want a rate-limit response surfaced as its own named condition, so that it is
     not reported as a generic outage.
114. As the Admin, I want staleness reported by naming the affected Instruments, so that I know
     what is stale rather than that something is.
115. As the Admin, I want securities priced by a market-data port supplying current quote and
     daily close history per Listing, so that a Depot has a current value and historical
     valuations exist.
116. As the Admin, I want identity resolution and pricing to be separate ports, so that mapping
     an identifier and fetching a price can use different providers.
117. As the Admin, I want an Instrument the provider does not cover marked unpriced and excluded
     from totals with a visible note, so that it is never valued at zero.
118. As the Admin, I want every foreign-currency amount converted to EUR by the euro reference
     rate for the event date, with the rate and its date stored alongside the converted amount,
     so that a re-run of the report reproduces the same figure.
119. As the Admin, I want weekend and holiday dates resolved by one documented rule applied
     consistently, so that conversions are defensible.
120. As the Admin, I want stablecoin EUR values taken from the daily reference rate rather than a
     crypto price provider, so that poor coverage cannot manufacture a phantom loss.
121. As the Admin, I want daily closes stored per Instrument with source attribution and a
     backfill for a chosen range, so that charts and historical valuations do not depend on a
     provider being up.

### Portfolio

122. As the Admin, I want one holdings view covering crypto, securities and cash, so that I can
     see my whole net worth in one place.
123. As the Admin, I want each position to show quantity, average cost, current value, unrealised
     result and where it is held, so that I can judge it without opening it.
124. As the Admin, I want cost basis taken from Tax Lots rather than summed from inflows, so that
     the portfolio and the tax report cannot disagree.
125. As the Admin, I want to group holdings by asset class, Platform and custody type, so that I
     can see the portfolio the way the question requires.
126. As the Admin, I want unpriced, ignored and dangerous positions marked and excluded from
     totals, so that a total is never quietly wrong.
127. As the Admin, I want values rendered in a selected display currency while German tax figures
     stay in EUR, so that presentation never affects a tax number.
128. As the Admin, I want allocation charts to state how many positions they chart versus how many
     I hold, so that a chart never implies completeness it does not have.
129. As the Admin, I want positions below a threshold grouped rather than dropped, so that small
     holdings are summarised instead of hidden.
130. As the Admin, I want a portfolio value chart over selectable ranges backed by stored
     snapshots plus live value, so that I can see development over time.
131. As the Admin, I want the chart to distinguish value change from contributions and
     withdrawals, so that a deposit does not read as a gain.

### Derivatives

132. As the Admin, I want imported futures fills stored immutably and positions derived from them,
     so that the reconstruction can be re-run without re-fetching.
133. As the Admin, I want derived positions wiped and rebuilt idempotently per source, so that a
     re-derivation cannot leave residue.
134. As the Admin, I want derivation to use position side, reduce-only and per-fill realised
     result where the venue exposes them and fall back to documented net accounting otherwise,
     so that precision follows the data available.
135. As the Admin, I want manually entered and derived positions to share one model and one tax
     treatment, so that only their origin differs.
136. As the Admin, I want funding payments attributed to the position open at the payment
     timestamp, so that net result is complete.
137. As the Admin, I want funding, trading fees and realised result stored separately and summed,
     so that each is traceable.
138. As the Admin, I want unattributable funding surfaced rather than dropped, so that nothing
     disappears.
139. As the Admin, I want a coin-margined close to produce both its capital-income event and a Tax
     Lot for the coin received at its EUR value at close, so that the settlement asset enters the
     ledger with a correct basis and its own holding period.
140. As the Admin, I want bot-run strategies summarised as an aggregate with constituent fills
     retrievable, so that thousands of micro-fills do not drown the ledger.
141. As the Admin, I want the capital-income figure from an aggregate to equal the sum over its
     fills, so that summarising never changes a number.
142. As the Admin, I want a dust sweep recorded as one aggregate disposal with its constituents
     retrievable, so that a routine housekeeping action does not generate dozens of report lines.

### Crypto tax — §23 and §22

143. As the Admin, I want each acquisition to mint a Tax Lot and each disposal to consume lots
     FIFO within the same Account and Instrument, so that matching reflects where assets sat.
144. As the Admin, I want each lot consumption to record quantity, basis, proceeds, holding period
     and long-term flag, so that every figure is traceable to its lots.
145. As the Admin, I want a disposal exceeding available lots to be a hard error naming the
     shortfall, so that a zero-basis fill is never silently invented.
146. As the Admin, I want the whole calculation rebuilt from the beginning of time on every run,
     so that no incremental state can drift.
147. As the Admin, I want disposals of assets held more than the statutory period treated as
     exempt and excluded from the total while remaining visible in the appendix, so that the
     figure is right and the working is shown.
148. As the Admin, I want the holding period computed between absolute instants, so that it is
     unaffected by timezone.
149. As the Admin, I want a self-transfer and a **Staking Delegation** to leave the holding period
     untouched, so that moving or committing my own coins costs me nothing.
150. As the Admin, I want the annual all-or-nothing **Freigrenze** applied with year-aware limits
     drawn from configuration, so that a small year is correctly free and a year over the line is
     fully taxable.
151. As the Admin, I want the report to show headroom or overshoot against the Freigrenze
     explicitly, so that I can see how close a year was.
152. As the Admin, I want staking, lending interest, mining and qualifying airdrops valued at
     market value on receipt and simultaneously minting a lot at that basis, so that income and
     cost basis agree.
153. As the Admin, I want that income pooled under its own annual Freigrenze applying "less than",
     so that exactly the threshold is already fully taxable.
154. As the Admin, I want the report to state the taxable amount rather than a euro tax owed for
     this category, so that it does not assert a marginal rate it cannot know.
155. As the Admin, I want delegation tracked as an informational marker per Account and Instrument,
     so that it never acquires tax meaning.
156. As the Admin, I want delegation events found during import surfaced as warnings rather than
     imported as transactions, so that only I decide whether coins moved.
157. As the Admin, I want the tax year determined by German local date while timestamps stay
     absolute instants, so that a trade just after New Year lands in the right year.

### Capital income — §20, unified

158. As the Admin, I want every source of capital income reduced to one **Section 20 Event**
     carrying its category, so that the allowance and offsetting rules apply to the combined
     picture rather than one silo.
159. As the Admin, I want futures, share disposals, fund disposals, dividends, distributions,
     interest and Vorabpauschale all to emit that same shape, so that adding a source needs no
     engine change.
160. As the Admin, I want no producer of capital income to know anything about allowances, pots or
     rates, so that tax logic lives in exactly one place.
161. As the Admin, I want losses from share sales to offset only gains from share sales, so that
     the figure I declare survives scrutiny.
162. As the Admin, I want losses in the other-capital-income pot to offset other income in that
     pot including dividends, so that offsetting is neither too broad nor too narrow.
163. As the Admin, I want per-year loss caps drawn from configuration rather than constants in
     logic, so that a statutory change is a configuration change.
164. As the Admin, I want each pot's balance for the year shown, so that form lines can be filled
     directly.
165. As the Admin, I want each pot to carry unused losses forward across years within itself, so
     that a losing year reduces a later winning year.
166. As the Admin, I want carryforwards never to cross pots, so that offsetting stays lawful.
167. As the Admin, I want a year that produced or consumed a carryforward to state the amount, the
     pot and the year it came from, so that the chain is auditable.
168. As the Admin, I want each pot to accept an opening carryforward entered from an assessment
     that predates the ledger, so that a loss established outside the app still shelters income
     inside it.
169. As the Admin, I want each dividend to record gross, foreign withholding with its country,
     German tax withheld at source, and net received, so that I can see what is taxable and what
     is already paid.
170. As the Admin, I want foreign withholding reported as creditable up to the treaty limit with
     any excess shown as reclaimable from the source country, so that I know which part is
     recoverable and from whom.
171. As the Admin, I want a fund distribution to carry its Teilfreistellung before entering its
     pot, so that only the taxable share is pooled.
172. As the Admin, I want income from a withholding broker distinguished from income I must still
     declare, so that I do not re-declare what is settled.
173. As the Admin, I want securities disposals computed FIFO within Depot and Instrument with no
     holding-period exemption, so that the gain matches what a German broker would compute.
174. As the Admin, I want gain computed as proceeds less cost basis less transaction costs, all in
     EUR at the rates of their respective event dates, so that currency movement on the security
     is part of the gain rather than a separate item.
175. As the Admin, I want fund gains reduced by Teilfreistellung and by Vorabpauschale already
     taxed on the consumed lots, so that the same euro is never taxed twice.
176. As the Admin, I want a partially consumed lot to keep its remaining basis and its accumulated
     Vorabpauschale proportionally, so that a partial sale does not distort the remainder.
177. As the Admin, I want share gains routed to the shares pot and fund, bond and certificate
     gains to the other-income pot, so that offsetting follows the statute.
178. As the Admin, I want Vorabpauschale computed per fund per year from the start-of-year value,
     the annual base rate and the statutory factor, capped at the year's increase in value and
     reduced by distributions, so that the advance lump sum is right.
179. As the Admin, I want the calculation to distinguish the year it derives from and the year it
     is declared in, so that an advance lump sum lands in the correct return.
180. As the Admin, I want no Vorabpauschale computed for a fund I did not hold at the accrual
     moment, so that a fund sold during the year does not generate one.
181. As the Admin, I want a fund whose value fell over the year to produce zero, so that a loss
     never becomes deemed income.
182. As the Admin, I want the base rate and the fund's start- and end-of-year redemption values
     entered as per-year configuration with their source shown, so that nothing statutory is
     hardcoded.
183. As the Admin, I want the app to refuse to compute a year whose base rate or fund valuation is
     unset, so that it never substitutes an approximation silently.
184. As the Admin, I want accumulated Vorabpauschale tracked per lot and deducted from the gain on
     eventual sale, so that I am not taxed twice on the same amount.
185. As the Admin, I want the **Sparerpauschbetrag** applied once as a deduction across the
     combined total after offsetting, so that it is never applied per source.
186. As the Admin, I want any portion of the allowance already consumed at source by a
     **Freistellungsauftrag** deducted first, so that the app never claims more allowance than
     exists.
187. As the Admin, I want the flat rate applied with the exact church-tax formula including its
     deduction effect, so that the resulting figure is the one that belongs on the form.
188. As the Admin, I want the report to note that a personal-rate comparison may apply without
     computing it, so that it flags the possibility without asserting a rate it cannot know.
189. As the Admin, I want all statutory constants held as per-year configuration with their source
     cited, so that a rule change is data rather than a code change.

### Reporting

190. As the Admin, I want a generated report frozen with its computed figures and a fingerprint of
     its inputs, so that what I filed is exactly what I can reproduce.
191. As the Admin, I want a report to move from draft to final and a final report to be immutable,
     so that a filed figure cannot change.
192. As the Admin, I want regeneration to create a new report rather than mutate an existing one,
     so that history is preserved.
193. As the Admin, I want report sections organised the way the German forms are, so that
     transcription is mechanical.
194. As the Admin, I want each figure to name its form line where the mapping is unambiguous and
     say so where it is not, so that I am never left guessing.
195. As the Admin, I want amounts withheld at source shown separately from amounts to declare, so
     that I do not double-report.
196. As the Admin, I want each disposal line to show acquisition and disposal dates, quantity,
     basis, proceeds, fees, holding period, exempt or taxable, pot, and the lots consumed, so
     that I can answer a question without re-deriving anything.
197. As the Admin, I want lines resting on estimated basis marked and the total exposed to
     estimation stated, so that the report's confidence matches its evidence.
198. As the Admin, I want the report exportable as CSV and PDF containing the same figures, so
     that I have both a machine-readable and an archival copy.
199. As the Admin, I want a report whose input fingerprint no longer matches flagged as stale
     wherever it is shown, so that I never file an out-of-date figure.
200. As the Admin, I want the staleness notice to name what changed, so that I can judge whether
     it matters.
201. As the Admin, I want the fingerprint to cover statutory configuration as well as
     transactions, so that correcting a rate marks every report resting on it as stale.
202. As the Admin, I want a final report never silently recomputed, so that regeneration is always
     an explicit act.
203. As the Admin, I want a year-over-year summary per regime showing carryforward in and out per
     pot, so that I can see trends and shelters across years.
204. As the Admin, I want years with unfinished prerequisites marked as blocked with the reason, so
     that I know what stands between me and a figure.
205. As the Admin, I want finalisation refused while known blockers exist, so that I do not file on
     top of a gap I already knew about.
206. As the Admin, I want each blocker to link to the screen that resolves it, so that fixing it is
     one click rather than a search.
207. As the Admin, I want to be able to override a blocker with an acknowledgement recorded on the
     report itself, so that the decision travels with the figure.
208. As the Admin, I want to export my ledger in a form an independent tax tool can import, so that
     I can have a second engine compute the same year from the same transactions.

### Automation and onboarding

209. As the Admin, I want price updates, snapshots and syncs to run on a schedule I control with
     manual run-now, so that the app stays current without me clicking.
210. As the Admin, I want each task to record last run, duration, outcome and error, and overlapping
     runs prevented, so that a stuck task is visible and cannot pile up.
211. As the Admin, I want a checklist from empty database to first tax report whose state is derived
     from real data, so that I know what still needs doing.
212. As the Admin, I want every empty state to explain what to do next and every error to name what
     failed and the action that fixes it, so that I am never stuck without a next step.

## Implementation Decisions

### Approach

- New repository. v1 is not migrated: it stays runnable as a read-only reference. The one-shot
  legacy database importer is dropped — every source file is available, and v2's shapes differ
  enough (balanced legs, cash Instruments, evidence-scoped Accounts, chain-and-contract keys)
  that a v1 reader would map into shapes that no longer exist.
- v1's statutory test fixtures are ported first and act as a **parity oracle**: v2 must reproduce
  v1's figures on v1's fixtures, and every divergence must be explained as a deliberate fix.

### Stack

- **Backend:** Python 3.14, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2 with pydantic-settings,
  psycopg 3, uvicorn, httpx. Tests with pytest; linting and formatting with ruff. Dependencies
  managed with pip.
- **Frontend:** React 19, TypeScript 7, Vite 8, Tailwind 4, shadcn/ui, TanStack Query, Zod 4.
  Tests with Vitest and Playwright. Package management with pnpm.
- **Database:** Postgres, in Docker Compose locally.
- No Makefile. `pnpm` scripts at the repository root are the single documented entry point;
  Python tasks are invoked through them.
- Layout is the API service and the web client. There is no shared TypeScript package — its only
  purpose in v1 was sharing types with a mobile client that is out of scope.

### Deployment and CI

- Deployment is Dokploy on a VPS reachable only over a private network. Dokploy's own auto-deploy
  is disabled; CI triggers the deployment through Dokploy's API after all checks pass, joining the
  private network for the duration of that job.
- CI is decomposed: an orchestrating workflow that calls one reusable workflow per concern (API,
  web, end-to-end, deploy), plus composite actions for toolchain setup so it is defined once. The
  deploy job depends on all check jobs, so the gate survives the decomposition.
- Migrations run as a release step, not at application startup.

### Domain model

- **Platform** replaces v1's `Exchange`, with kinds covering exchange, cold storage, software
  wallet, broker and bank. **Account** replaces `Wallet`. **Depot** is vocabulary for an Account
  under a broker Platform — no table, no subtype, nothing branches on it.
- An Account's scope is as fine as its Platform can evidence. Where an export names an account and
  its extended public key, that is the Account; where it names only an address, the Account is one
  device and one chain. Mixed granularity across Platforms is intended.
- `withholding` lives on the Platform, with a nullable per-Account override for brands operating
  through several entities with different tax status.
- A nullable Freistellungsauftrag amount lives on the withholding Platform. Absent means none.
- **Instrument** unifies crypto assets, securities and cash under `family`. Crypto keys on chain
  and contract where a contract exists and on symbol only for native coins; symbol is never
  authoritative for identity resolution. Securities key on ISIN. **Listing** (Instrument, venue,
  quote currency) is its own concept and is what a price source points at. Each Instrument keeps
  an identifier history so a lot survives an identifier change.
- **Cash** is an Instrument family. EUR is the numéraire — its movement is not a disposal. All
  other cash Instruments are ordinary assets with a Haltefrist, which brings foreign-currency
  positions into the §23 engine rather than leaving them as a noted gap.
- **Transaction** is a set of balanced legs. A fee is a leg, and its tax treatment is read from the
  regime of the leg it was charged against — which resolves currency-conversion fees, trading fees
  and futures fees uniformly with no per-type special cases.
- **Stance** on an Instrument replaces both `Untrusted Asset` and `De-minimis Inflow`:
  `unacknowledged` (the default for anything new; inflows record but mint no lot), `kept`,
  `ignored`, `dangerous`. `dangerous` is global to the Instrument; `ignored` and `kept` are per
  Account. Acknowledging an unsolicited inflow prompts for whether it was received for a
  counter-performance, defaulting to no — meaning a zero-basis lot and no income event.
- **Tax Lot** is a materialisation, not a source of truth. The transaction ledger is the only
  truth; lots and their disposals are derived in full and stored only so holdings and reports need
  not replay the ledger. Each materialisation records the fingerprint of the inputs that produced
  it, reusing the report-staleness mechanism rather than inventing a second consistency scheme.
- **Opening Balance** distinguishes *acquisition date known, basis estimated* from *both
  reconstructed*. Conservative dating applies only to the second. This matters because an exempt
  disposal's gain is excluded from the total entirely, so for a long-held position the acquisition
  date is load-bearing and the basis is cosmetic — while for securities, which have no holding-
  period exemption, the basis is always load-bearing.

### Tax engine

- One `Section20Event` is the sole input to the §20 engine. It carries: the date it occurred, its
  category (`aktien` | `sonstige` | `termingeschaefte`), the gross amount, a Teilfreistellung rate,
  German tax withheld at source split into its components, foreign withholding with its source
  country, and a reference to the record that produced it.
- The engine, per year and in this order: group by category; net within category; apply that
  category's per-year loss cap; consume that category's carryforward; carry the remainder forward
  within the same category; sum surviving categories; apply the Sparerpauschbetrag once, less any
  portion consumed at source; apply the rate.
- Every producer of capital income emits events and knows nothing about pots, allowances or rates.
  Futures must be built as an emitter, never as a calculator — this is the structural decision that
  determines whether securities can be added without rewriting the derivatives work.
- Each pot accepts an opening carryforward as per-year configuration, seeded from an assessment
  that predates the ledger. Absent means zero, not unknown.
- Vorabpauschale distinguishes the year it derives from and the year it is declared in. It requires
  the fund to have been held at the accrual instant, computes as the base yield less distributions
  floored at zero and then capped at the year's increase in redemption value, and is reduced by
  Teilfreistellung before entering its pot. The base rate and the fund's start- and end-of-year
  redemption values are entered per year; the app refuses to compute a year with any of them unset
  rather than substituting a market close.
- A coin-margined close emits a Section 20 Event for the result **and** mints a §23 Tax Lot for the
  settlement asset at its EUR value at close time. This follows from balanced legs and needs no
  special rule.
- All statutory constants — Freigrenzen, loss caps, allowance amounts, rates, base rates — are
  per-year configuration rows with a cited source. Logic reads them; it does not branch on years.

### Ingestion

- Four ports, each with a fake for tests: exchange adapter, broker adapter, CSV connector, and
  **Address Indexer** (chain plus address to normalized transfers — the mode for a self-custody
  wallet with neither an export nor an account).
- Market data is split into two ports: identifier resolution (identifier to Listings) and pricing
  (Listing to quotes and daily closes), because no single free-tier provider does both well.
- Exactly one authoritative ingestion mode is declared per Account. A second source may reconcile
  against it but may not write transactions — this makes double-counting structurally impossible
  rather than merely unlikely.
- Each connector declares the timezone and units its venue exports in and converts on the way in.
  An export in local time is never tagged UTC; sub-units are normalised.
- Adapters to build: OKX, Coinbase, Pionex (portable from v1), Trading 212, Bitpanda. Statement
  import for eToro. CSV connectors: Ledger, BitBox (both portable from v1), plus a generic
  column-mapping importer. Address Indexer: Solana first, with the port able to take other chains.
- Platforms with no ongoing activity are served by Opening Balance and reconciliation, not by an
  adapter.
- An independent tax tool is used as a downstream verifier only: v2 exports its ledger in that
  tool's import format so both engines compute the same year from identical transactions. Data
  never flows the other way.

### Cross-cutting

- Money and quantities are fixed-point decimals end to end, including in JSON. Never floats.
- Rounding is defined once and applied at presentation and statutory boundaries only.
- Every import and sync is dedup-keyed on source and external identifier; re-running changes
  nothing.
- Timestamps are stored as absolute UTC instants. Only interpretation into a tax year uses German
  local time.
- Layering is enforced: routers validate, services decide, repositories query. Business logic in a
  router is a review failure.
- The staleness fingerprint is per-entity — a count plus a digest per input class (transactions,
  corporate actions, instrument classifications, FX rates used, statutory configuration) — so that
  a change can be described, not merely detected.

## Testing Decisions

A good test here describes external behaviour: given these transactions and this configuration,
the report says this. It never asserts how a service is layered, which repository was called, or
what an intermediate structure looks like. A test that would still pass after the rule it covers
was deleted is not a test of that rule.

Four seams, in descending order of how much should live at each:

**1. The HTTP API against a real Postgres.** The default seam and where almost every test belongs.
Covers ledger operations, holdings, import preview and commit, reconciliation, report generation
and finalisation, and settings. Ports are replaced with fakes; the database is not. An in-memory
substitute is not acceptable — the queries and the migrations are part of what is under test.

**2. The tax engine as a pure function** — transactions and configuration in, annual result out.
This is the one place a lower seam is justified, because every statutory rule needs a test that
fails individually and loudly. Each such test names the paragraph it implements, and its fixture
must be one that would fail if the rule were dropped. Prior art: v1 already isolates its tax
intermediates as pure structures with no database dependency, and its fixtures port directly.

Boundary cases get explicit tests rather than being assumed to fall out: both sides of a tax-year
boundary in winter and summer time; a Freigrenze at, just below and just above its threshold; the
allowance exactly consumed; a loss exactly at a pot's cap; a lot exactly exhausted; a disposal one
day inside and one day outside the holding period.

**3. Ports against recorded fixtures.** Each adapter, connector and indexer is tested by feeding it
recorded venue responses and asserting the normalized records it emits. No live calls in CI. Each
connector's declared timezone and unit handling is tested explicitly, including a venue that
exports in local time and one that exports in sub-units — both are real cases, and both silently
produce wrong tax years or wrong quantities if mishandled.

**4. Playwright against the built application.** A small number of critical journeys only: first-run
setup and login, recording a transaction by hand, running an import preview and committing it, and
generating a report. Deliberately no broad component-test layer — individual React components are
not tested in isolation.

Migrations are tested up and down against a seeded database in CI.

## Out of Scope

- **Mobile client.** No Android or iOS application, and no shared TypeScript package to support one.
- **Notifications.** No push, chat or webhook channels. A failed sync is visible on the health panel.
- **In-app backups.** Database backups are handled by the deployment platform and a documented dump
  procedure, not by a backup subsystem inside the application.
- **Audit log.** No append-only record of consequential actions.
- **Money-weighted return and performance analytics.** Realised and unrealised results are shown;
  internal rate of return is not computed.
- **Upcoming income calendar.** No forecast of announced dividend or distribution dates.
- **Migrating v1's database.** History is re-established from its sources.
- **Filing.** The application states taxable amounts. It does not submit anything to any authority.
- **Trading.** No order placement and no write access of any kind to any venue. Read-only
  credentials only.
- **Multi-user.** No roles, no sharing, no tenancy.
- **Tax regimes other than German**, and no computation of a personal-marginal-rate comparison —
  the report notes that one may apply and stops there.
- **Real-time market data**, order books, or sub-minute price granularity.
- **Physical-delivery reclassification of derivatives** beyond flagging candidates for review.

## Further Notes

**The first deliverable is the 2026 tax return**, which is not due until well into the following
year. That deadline is comfortable, but it sets the order: the crypto side carries far more history
than the securities side, and securities cannot be exercised against real data until positions
exist.

**Suggested phase order.** Each phase ends in something usable rather than a layer:

1. Skeleton — repository, CI, deployment, authentication, Platform/Account/Depot, migrations, seed.
2. Ledger — balanced-leg Transactions, Instruments, Cash, the Stance inbox, manual entry, Opening
   Balances for long-held positions, holdings.
3. Crypto tax — FIFO per Account, Haltefrist, Freigrenzen, income pooling, report and appendix.
4. Capital income — the Section 20 Event engine first, then futures built as an emitter of it;
   pots, carryforward, seeded openings.
5. Live crypto ingestion — exchange adapters, the Address Indexer, reconciliation.
6. Securities — Depot, ISIN and Listing, broker adapters and statement import, market data,
   disposals, dividends and foreign withholding, Teilfreistellung.
7. Remaining — corporate actions, health panel, ledger export for independent verification, and
   Vorabpauschale.

**Vorabpauschale ships unexercised.** Nothing can accrue one until a fund has been held across a
year boundary, so its first live run is over a year away and its correctness until then rests
entirely on hand-computed fixtures. It is the safest thing in the plan to defer and the most
dangerous to trust without them.

**Deliberately parked, each with a trigger and no rework cost:**

- The Freistellungsauftrag amount — the field exists and defaults to none; a value is entered when
  the brokerage accounts are configured.
- Opening carryforward balances per pot — entered when the corresponding assessments exist.
- Whether the securities-holding brokers carry positions predating the ledger — resolves when their
  statements are exported. If they do, those need real acquisition prices, because securities have
  no holding-period exemption and the cost basis is always load-bearing.

**To verify rather than assume during phase 6:** the exact statement format offered by each broker
without an API, and the shape and coverage of each broker API. Neither should be designed against
from memory.

**Repository hygiene.** This repository is public. No account-derived figures — balances, results,
position or trade counts, holdings — may appear in code, tests, fixtures, commit messages or issue
files. Statutory constants are fine.
