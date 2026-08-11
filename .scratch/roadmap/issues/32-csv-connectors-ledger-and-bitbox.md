# 32 — CSV connector port; Ledger and BitBox

**What to build:** The port for importing a venue's exported file, proven by two real hardware-wallet connectors. Each declares the file it expects, the timezone it exports in, and the units it uses — because an export in local time silently produces wrong tax years, and one in sub-units silently produces wrong quantities.

**Blocked by:** 31

**Status:** implemented

- [x] A connector port with a fake, plus a registry so adding one touches no service, router or screen
- [x] Two hardware-wallet connectors ship and work end to end through preview and commit
- [x] Each connector declares the file it expects and rejects a mismatched file with a clear message rather than mis-parsing it
- [x] Each connector declares its venue's timezone and converts to UTC; an export in local time is never tagged UTC
- [x] Each connector declares its units and normalises them; a sub-unit export is never taken as a whole unit
- [x] A connector that cannot support a variant refuses that file explicitly
- [x] Connectors are tested against recorded fixtures, with no live calls in CI
- [x] The timezone and unit handling of each connector is tested explicitly

## Comments

Implemented. The port lives in `ports/csv_connector.py` — a connector declares its registry
name, the export to produce (`expects`, shown by the picker), the IANA timezone its bare
timestamps are read in, and `parse(content) -> ParsedFile` of normalized rows (UTC, whole
units) plus warnings; a wrong file or unsupported variant raises `FileRejectedError` with one
sentence. The registry (`ports/connectors.py`) is served through a dependency
(`adapters.get_csv_connectors`) exactly like the exchange adapters; `services/csv_imports.py`
resolves symbols and hands rows to ticket 31's evaluation; `routers/csv_imports.py` is generic
over the registry (`GET /csv-connectors`, `POST /csv-imports/preview`, `POST /csv-imports`).
The Imports screen grew the upload → preview → commit flow, rendered from the registry
endpoint, and a Playwright journey drives a BitBox file through it in the real browser.

How each criterion is held:

- **Port, fake, registry**: `test_csv_imports.py` drives an invented connector end to end
  through the same dependency production reads — proof that a new connector is a registry
  entry and nothing else.
- **Timezone**: Ledger Live declares UTC (the app itself writes ISO 8601 UTC). The BitBoxApp
  writes the exporting computer's clock with no offset, so the connector declares
  Europe/Berlin — the deliberate assumption for this self-hosted German-tax instance, stated
  in the picker ("Bare timestamps are read as Europe/Berlin time and converted to UTC") so it
  is a visible fact, not a silent one. Tests pin a July timestamp to −2 h and a January one to
  −1 h, so DST is proven, and an offset-carrying variant converts by its own offset.
- **Units**: BitBox amounts and fees arrive in smallest units; the Unit column names the
  divisor, the Fee Unit column rules the fee (falling back to the amount's unit), an unknown
  unit or a fee in another coin's unit refuses the file. Ledger Live declares whole units.
- **Variants refused**: wrong header, unreadable timestamp or amount, unknown BitBox
  type/unit, a Ledger export spanning several accounts (judged on every confirmed row, so an
  account represented only by skipped rows still refuses), and one BitBox transaction stating
  rows in two coins.
- **Fixtures**: recorded export shapes carried over from v1's captured files, committed as
  anonymised inline fixtures — this repo is public and forbids personal financial data, so
  literal captured exports cannot be committed. No network anywhere in the tests.

Decisions worth recording:

- **The provenance source is scoped per Account** (`bitbox:<account_id>`): dedup is keyed on
  (source, external id), and a transfer between two of the Admin's own wallets appears in both
  exports under one transaction id — both sides are facts, so two Accounts fed by the same
  connector must not swallow each other's rows. A test pins this.
- **Symbols resolve, never mint** (ADR-0010): a file naming an Instrument the ledger does not
  hold refuses whole with "create it, then import again", the same rule as the exchange sync.
  Hardware-wallet exports state no chain or contract, so auto-creation would forge identity.
- **BitBox `sent_to_yourself` records the network fee only** — the coins never leave the
  Account, so v1's treatment (a transfer-in of the full amount) minted a phantom acquisition;
  only the fee is a fact, and a warning says so. One with no fee is left out, with a word.
- **Ledger Live OUT amounts keep the fee inside** — the export's amount is the whole balance
  change, so a separate fee leg would count the fee twice.
- **Staking operations stay unimported but never silent** (carried from v1): a delegation
  changes no ownership, but on chains where it parks coins in a pool contract the warning
  tells the Admin to record the move between their own wallets.
- No version bump — releases have not started; rides as `feat:` like tickets 10–31.
- Post-review fixes (two-axis review): the Fee Unit column is honoured (was silently divided
  by the amount's divisor), a mixed-coin transaction refuses (was summed across coins), the
  multi-account judgement reads every confirmed row (staking-only accounts slipped through),
  and the shared `cell` helper lives on the port module.
