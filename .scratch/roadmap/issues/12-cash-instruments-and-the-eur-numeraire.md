# 12 — Cash Instruments and the EUR numéraire

**What to build:** Cash becomes an Instrument like any other, so a balance can be held and later spent. EUR is the numéraire whose movement is not itself a disposal; every other currency is an ordinary asset.

**Blocked by:** 11

**Status:** done

- [x] Cash is an Instrument family, held per Account like any other holding
- [x] EUR is marked as the numéraire, and its movement creates no taxable event
- [x] A non-EUR cash Instrument is an ordinary asset — nothing in the model treats it specially
- [x] The numéraire is a property of configuration, not hardcoded into logic that could not express another
- [x] Holdings can show a cash position as its own line

## Comments

Implemented. One revision (`a3d1f6818004`) adds `is_numeraire` to `instrument` and mints EUR;
the rule the tax tickets will read lives in `services/instruments.py`.

How each criterion is held:

- **Cash is an Instrument family**: `create_cash` now opens the identifier history at birth
  (kind `symbol` — the currency code is cash's identity), exactly as the other families do,
  and a cash row flows through the same repository, service, API and UI as any Instrument.
  "Held per Account" has no code yet because Accounts are ticket 10 and holdings are lots
  (19/20); nothing here special-cases cash, so it will hold wherever holdings do.
- **EUR marked as the numéraire**: the migration inserts EUR flagged `is_numeraire` — with the
  chain, not the seed, because a deployment needs the numéraire before its first transaction
  and the seed never runs outside development. "Movement creates no taxable event" is delivered
  at its buildable extent as `movement_is_disposal(instrument)`: False for the numéraire, True
  for everything else, answered from the flag. Tickets 13/21 consume it; nothing anywhere
  compares a symbol to `EUR`.
- **Non-EUR cash is ordinary**: the seed adds USD; tests hold that it keys, resolves and
  disposes like any asset. No query, constraint or branch anywhere distinguishes non-EUR cash.
- **Configuration, not hardcode**: the designation is a flag the schema holds to at most one row
  (partial unique index) and to the cash family (CHECK). `designate_numeraire` moves it in one
  transaction, and a test proves CHF is expressible — another jurisdiction is an UPDATE, not a
  code change.
- **Holdings line**: satisfied structurally — a cash position is an ordinary Instrument row, so
  the holdings view (ticket 20 owns it, "Cash appears as its own line") needs no special case.
  Meanwhile the Instruments page already shows each cash row as its own line, with a
  signal-toned "numéraire" microlabel on the flagged row (tooltip explains the rule).

Decisions worth recording:

- **`GET /api/instruments` gains `is_numeraire`** — additive, so `feat:`/MINOR under the
  versioning policy; no other API surface.
- **The migration's downgrade deletes the EUR row it minted** (identifier history follows by
  cascade). Nothing references instruments yet; once Transactions (13) exist, walking below
  this revision is lossy by construction — the schema below it cannot say "numéraire".
- Post-review fixes (two-axis review): the `db` fixture moved to `conftest.py`; the repository's
  three reads share one column list; docstrings tightened.
