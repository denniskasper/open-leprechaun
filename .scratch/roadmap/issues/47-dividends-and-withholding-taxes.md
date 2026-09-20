# 47 — Dividends, distributions and withholding taxes

**What to build:** Income from securities is recorded gross with every tax already taken out of it, so the Admin can see both what is taxable and what has already been paid — and to whom.

**Blocked by:** 46

**Status:** done

- [x] Each dividend records gross, foreign withholding with its source country, German tax withheld at source split into its components, and net received
- [x] Foreign withholding is reported as creditable up to the treaty limit, with any excess shown as reclaimable from the source country rather than creditable
- [x] The app reports creditability; it never pursues a reclaim
- [x] A fund distribution carries its partial exemption before entering its category
- [x] Income from a withholding broker is distinguished from income that must still be declared
- [x] Interest is recorded and routed to the other-income category
- [x] Each event emits a Section 20 Event and computes no tax itself

## Comments

Implemented as a producer beside the engine, like ticket 46: `services/capital_income.py`
reduces every dividend, distribution and interest receipt to the figures one Section 20 Event
needs, and `section20.year_report` builds the event — the producer states pot and
Teilfreistellung rate, the engine alone exempts, nets, judges creditability and rates (ADR-0013).
The recording model is ADR-0022.

How each criterion is held:

- **Gross, both withholdings, net**: the in-leg stays the net that arrived, so cash balances
  reconcile to the broker; a `capital_income` row beside the Transaction declares the security
  that paid, the Quellensteuer with its source country and the German tax split into
  Kapitalertragsteuer, Solidaritätszuschlag and church tax — every amount in the received leg's
  own Instrument, converted at the event date (ADR-0017). The gross is derived, never stored.
  Schema CHECKs hold the amounts non-negative and the Quellensteuer and its country together;
  `services/transactions.income_defect` says the same in sentences before anything is written,
  and restricts the declaration to the three income types with exactly one received leg.
- **Creditable up to the treaty limit, excess reclaimable**: `section20.withholding_statement`
  is pure — each event's Quellensteuer is limited on its own gross by the country's treaty rate
  (§32d Abs. 5 EStG), so one dividend's unused room never shelters another's excess, then the
  figures sum per country. The limits are a new `treaty_limit` store, per source country with a
  cited source, entered on the statutory screen. A country that withheld with no limit entered
  refuses by name (`TreatyLimitUnsetError`, HTTP 409 on report generation).
- **Reports, never pursues**: the statement is figures on `Section20Year` and summary rows in
  the appendix; nothing anywhere acts on the reclaimable part.
- **Distribution carries its Teilfreistellung**: the rate follows the *payer* — any receipt paid
  by a fund wears that fund category's per-year rate, whatever type it was recorded under — and
  the engine exempts before the pot, as for disposals. A distribution naming no fund, a non-fund,
  or an unclassified fund refuses by name; the API also refuses to record one without its payer.
- **Withholding broker vs still to declare**: each receipt says whether its Depot's effective
  withholding behaviour (Account override first, then the Platform — ticket 43) is `at_source`;
  the year states both sides' gross (`settled_at_source_eur`, `to_declare_eur`).
- **Interest to the other-income category**: all three types state `sonstige`; the mapping
  moved from the engine into the producer, where ADR-0013 wants it.
- **One event, no tax**: the producer values and states; it reads no allowance, cap or rate.

Decisions worth recording:

- **Treaty limits key on the country alone, not the year** — a treaty article does not move
  with the calendar, and the per-year store's vocabulary is a closed CHECK-pinned list that one
  key per country would break (ADR-0022).
- **The ceiling is the treaty rate on the gross before Teilfreistellung.** Investor-level
  Quellensteuer on fund distributions is rare since the 2018 reform; refining the ceiling for it
  is left until a real case shows up.
- **The settled/to-declare split is gross, and the assessment is unchanged.** Every receipt still
  enters its pot, because the return restates all capital income and credits what was withheld;
  `allowance_used_at_source_eur` stays zero for the same reason. Netting the withheld tax against
  `TaxDue` is the Anlage-shaped report's (ticket 51) to decide.
- **Three new fingerprint classes** — `capital_income`, `treaty_limits`, `withholding_behaviour`
  — so correcting a withheld amount, a limit or a Depot's behaviour marks dependent reports
  stale. Reports and the lot materialisation stamped before this ticket read as stale once.
- **Imports carry no declaration yet**: an imported dividend's gross is its net until the Admin
  states what was withheld, and an imported distribution blocks its year until it names its
  fund. The broker adapters (tickets 48-50) are where a Normalized Dividend gains these fields.
- No pre-flight blocker was added: every new refusal already stops report generation, and a
  declaration changed afterwards marks the report stale.
- The `tax_treatment` reader allowlist changed: the §20 engine reads income through its
  producer, so `services/capital_income.py` replaced `section20.py` in the list.
- Post-review fixes (two-axis review): a distribution paid by a non-fund now refuses instead of
  silently taking a zero rate; the API requires a distribution's payer rather than leaving it to
  the web form; the ledger row states withheld amounts beside their currency
  (docs/agents/design.md); the treaty-limit panel uses `ErrorState`; one query, not two, reads
  the declarations; `Receipts.received` became `counted`.
- The web form and the treaty-limit panel were verified by typecheck and unit tests only — no
  browser was available in the implementing environment, so neither was looked at rendered.
