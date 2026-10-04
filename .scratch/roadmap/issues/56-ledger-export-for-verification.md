# 56 — Ledger export for independent verification

**What to build:** The Admin can hand their clean ledger to an independent tax tool and have it compute the same year from identical transactions — so a disagreement between two engines is a disagreement about rules, not about data.

**Blocked by:** 13

**Status:** done

- [x] The ledger exports in an independent tool's documented import format
- [x] Every transaction type in the vocabulary maps to something in that format, or is reported as unmappable rather than silently dropped
- [x] The export is deterministic: the same ledger produces the same file
- [x] Data flows outward only; nothing is ever imported back from that tool
- [x] The export carries no more than the tool needs

## Comments

Implemented as `services/ledger_export` behind `GET /api/ledger-export` (what the file carries
and what it leaves out) and `GET /api/ledger-export/cointracking.csv` (the file), with the
`Ledger → Export` screen at `/export`.

- **The independent tool is CoinTracking**, chosen by the Admin. The format is its documented
  hand-made CSV: the eleven columns from `Type` to `Date` plus the four optional ones it allows
  after the date, every field quoted. The header and the list of types were taken from its
  import pages (CSV import and Excel import, as archived — the live pages now sit behind a
  login), not from memory. **One thing is not from a primary source**: the date is written
  `dd.mm.yyyy hh:mm:ss`, which is what the tool's own export writes and its template's cell
  format suggests; the first real import should confirm it.
- **Every type maps**: trade → Trade; transfer in/out → Deposit/Withdrawal; spend → Spend;
  staking, lending, mining, airdrop → their namesakes; windfall → Airdrop (non taxable);
  dividend and distribution → Dividends Income; interest → Interest Income; a standalone fee →
  Other Fee. An opening balance → Income (non taxable) with its estimated basis in
  `Buy Value in Account Currency` — the one type that mints a holding at a stated value with
  nothing sold for it. A test fails when the vocabulary gains a type the table does not state.
- **Fees**: the tool's amounts include the fee and its fee column states it, where the ledger
  keeps the fee as its own leg. A fee in the currency of either side of its row is folded in
  (added to what was sold, taken off what was bought); a fee in a third asset, at another
  Account, or a second fee on one row is an `Other Fee` row of its own, so the balance agrees
  either way.
- **Left out, never dropped**: a Transaction the format cannot state is left out whole — half a
  trade would be a disagreement about data — and named with its reason beside the file: a
  security leg (the tool holds coins and currencies), an Instrument standing ignored or
  dangerous (outside the cost basis here too, per ADR-0012), a symbol that names more than one
  exported Instrument (the tool keys on symbol alone; an ignored namesake does not take the real
  asset with it), and a trade that is not one asset for one other at one Account.
- **Deterministic**: oldest first, ties broken by id, legs in id order, amounts as plain
  decimals, a fixed filename, no export timestamp. `Tx-ID` is `<transaction id>-<row>`, so a
  repeated upload is recognised as the same rows.
- **Outward only**: two GET routes, nothing else — every other method is refused, and no
  connector reads that tool.
- **No more than it needs**: amounts, symbols, `Platform - Account` as the place, the UTC
  instant. No note, no Account reference or access software, no chain or contract, no
  provenance, no price or value of this ledger's own beyond the opening balance's declared
  basis — the tool valuing the rows itself is the comparison wanted.
- The screen states what must be set in the tool before importing (account currency EUR, time
  zone UTC) because the file cannot carry either.
- **Out of scope, deliberately**: futures fills and funding, and corporate actions, are not
  Transactions and are not in the file; withholding declared beside an income event is not
  carried, so the tool sees the net that arrived. The screen says all three.
- **Two-axis review folded in**: a symbol collision is judged only over Transactions that
  actually reach the file, so a namesake left out for its shape takes nothing with it; a type
  with no mapping is reported as left out rather than failing the request; the fee's side is
  decided once, where it is absorbed; the row's place is named `account`, not "exchange"
  (CONTEXT.md), outside the tool's own column header; tests added for a second fee, a fee at
  another Account, a fee that would consume the whole receipt, an unattached fee beside several
  rows, a case-differing namesake and a name needing quoting. Left as they are: cash income is
  exported while a security's trade is left out, so the tool's cash balance at a Depot will not
  agree — it is a crypto tool and the numéraire carries no gain; `Platform - Account` is not
  escaped against a name containing the separator; no spreadsheet-formula neutralising, the
  file being read by the tool's importer; no Playwright spec, the agreed seams being the HTTP
  API and the web client.
- No version bump — rides as `feat:` like the tickets before it.
