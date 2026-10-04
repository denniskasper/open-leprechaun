# 50 — eToro statement import

**What to build:** A broker served by an exported statement rather than an API, using the connector port, so the Admin sees which mode each broker uses and neither is second-class.

**Blocked by:** 32, 43, 44

**Status:** done

- [x] A connector imports the broker's exported statement through preview and commit
- [x] Buys, sells, dividends and distributions with gross, withholding and net, plus fees and cash movements, are all imported
- [x] German tax withheld at source is recorded per event where the statement reports it
- [x] Foreign withholding is recorded per dividend with its source country
- [x] The connector declares the timezone and units the statement uses
- [x] The UI states that this broker is served by import rather than sync
- [x] Tested against recorded fixtures

## Comments

Implemented as a connector on the existing connector port (`ports/etoro.py` —
`EtoroStatementConnector`, registry key `etoro`), a standard-library workbook reader
(`ports/workbook.py`), and one widening of the port: a parsed file may carry a broker's statement
— the broker port's own Normalized records — instead of symbol rows. The decision is ADR-0027.

How each criterion is held:

- **Through preview and commit**: the statement goes through `POST /csv-imports/preview` and
  `POST /csv-imports` like any file. `services/csv_imports.py` routes by what the file yielded,
  never by a name: a statement lands by the same translation a Broker Adapter's harvest goes
  through (`services/broker_sync.py`, no diff), so deduplication, the authoritative-source rule,
  the withholding gate and batch reversal apply unchanged. The source is `etoro:<account>`.
- **Buys, sells, dividends, fees, cash movements**: the Account Activity sheet is the statement's
  ledger and the only sheet a record is made from. An opening is a purchase, a close a sale for
  the whole amount returned; a commission or stamp duty is its own row and becomes a fee charged
  against the security of the trade it names; deposits and withdrawals are cash movements;
  withdrawal and conversion fees are costs of the Depot; interest is income naming no payer.
  Everything is recorded as a dividend, never a distribution — a fund's Teilfreistellung follows
  the payer (as on Trading 212).
- **Gross, withholding and net**: the activity states the instant and the net; the Dividends
  sheet, joined by Position ID, day and net, states what was withheld. The net is the in-leg, the
  withholding is declared beside it (ADR-0022), the gross is their sum.
- **German tax withheld at source, where the statement reports it**: it reports none — no sheet
  has a column for it — so the connector declares none rather than a zero. The path is proven
  through the port's fake (`test_statement_imports.py`): the three components land per event.
- **Foreign withholding with its source country**: recorded per dividend. The statement names no
  country, so the one recorded is the one the paying security's ISIN names, and the preview says
  so in a sentence — it is wrong for a depositary receipt taxed elsewhere, which the Admin
  corrects on the Transaction.
- **Timezone and units declared**: UTC; whole US dollars and whole units, fractions included —
  in the picker's copy and held by tests. A statement of an account kept in another currency is
  refused, as is a translated or older layout, each with what to do.
- **The UI states the broker is served by import**: the Platforms page already says "Served by
  import — it stays current only as far as the last statement imported" for a broker whose Depot
  an import declared itself authoritative for (ticket 48); a committed statement is exactly that,
  and a test pins the declaration. The Imports page now offers the workbook: the picker follows
  the connector's declared file format, and the preview states the period the statement covers.
- **Recorded fixtures**: `tests/fixtures/etoro/recorded.json`, built into a real .xlsx by the
  tests so the reader is under test with it.

Decisions worth recording:

- **The fixture is authored, not recorded.** The statement is a workbook (XLSX or PDF; no CSV).
  Its sheets, headers, row-type vocabulary and cell conventions were taken from open-source
  readers of real statements (masbug/etoro-edavki, Yozer/tax-calculations, PBLIZZ/
  portfolio-tracker, GeiserX/DeclaRenta, nenadjakic/investiq), not from eToro's own
  documentation, and no account was available to record from. These readings want confirming
  against a first real statement: that timestamps are UTC; that a closing row's Amount is the
  whole amount returned; that a trade's Amount excludes its commission; the Account Summary's
  label/value layout (period and currency); how a real export stores strings and dates (shared
  and inline strings, text and date serials are all read); and what a partial close does to a
  Position ID.
- **The Account Activity sheet has no ISIN.** It stands only on a closed position and on a
  dividend. The connector joins by Position ID, then by ticker within the file. A position still
  open that never paid is named by its ticker alone — a resolution hint (ADR-0010): exactly one
  security in the ledger may answer to it, by symbol or ticker alias, and the row lands under its
  ISIN, the preview saying which. Otherwise the row is left out with a sentence and the rest
  lands; re-importing the same file later brings it in. For this, the broker port's security may
  state no ISIN — the one change to that port.
- **Nothing is made from the Closed Positions sheet.** A sale whose purchase predates the
  statement lands with a warning rather than a purchase rebuilt from that sheet: with partial
  closes unverified, a rebuilt purchase could count units twice.
- **Passed over by name**: a leveraged or short position (a contract for difference) and a coin
  (no ISIN; the broker port names nothing by ticker), each once with the rows that moved its cash
  and their net; a split; a trade row with no units or no positive amount; a cash row signed
  against its type; and any row type the connector does not know — the vocabulary is unpublished,
  so an unknown word never refuses the file. The cash these moved is not booked, and the preview
  says the Depot's cash will differ.
- **No Original Amount.** The account is kept in dollars and the legs are dollars; the
  statement's per-position FX columns stand only on closed positions and their direction is
  unverified, so the amount as priced is not stated.
- **An identifier is what the row states.** A trade is `<position>:open` or
  `<position>:close:<instant>`; anything else is its type, instant and amount, numbered where a
  statement lists the same thing twice — so two statements that each cut such a pair in half
  would disagree.
- **No new dependency.** A workbook is a zip of XML; the reader is the standard library, bounded
  against oversized parts and document-type declarations, numbers kept as Decimals.
- **Two-axis review folded in.** Spec axis: a fee listed before its trade now attaches; an
  opening that states its leverage is no security even while open; a cash row signed against its
  type is named instead of flipped; a close that returned nothing no longer refuses the file; a
  dividend booked a day off the sheet's date keeps its withholding; a ticker the ledger answered
  is said in the preview. Standards axis: no float on the date path; a workbook dated from 1904
  is refused. Accepted as-is: the port, routes and client keep "csv" in their names though one
  connector now reads a workbook; the fixture file is named like its siblings; a broker with a
  statement connector reads "served by manual entry" until its first import.
- Not viewed in a browser, and the Playwright journeys were not run: the Imports change is
  covered by unit tests and typecheck.
- No version bump — rides as `feat:` like the earlier adapters.
