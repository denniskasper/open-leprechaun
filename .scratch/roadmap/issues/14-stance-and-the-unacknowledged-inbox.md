# 14 — Stance and the unacknowledged inbox

**What to build:** Anything arriving that the Admin has never classified waits in an inbox instead of entering the cost basis. Classifying it is a deliberate act with three outcomes.

**Blocked by:** 13

**Status:** ready-for-agent

- [x] A new Instrument carries a **Stance** of `unacknowledged` by default
- [x] An inflow of an unacknowledged Instrument is recorded as a transaction but mints no lot
- [x] An inbox lists unacknowledged Instruments with the stances `kept`, `ignored` and `dangerous`
- [x] `dangerous` applies to the Instrument globally; `ignored` and `kept` apply per Account
- [x] Acknowledging an unsolicited inflow asks whether it was received for a counter-performance, defaulting to no
- [x] An ignored or dangerous position stays visible with a clear warning rather than being hidden
- [x] An ignored or dangerous Instrument can never acquire a price source

## Comments

Implemented. One revision (`2b99560def98`) creates `instrument_stance` and widens the
transaction vocabulary with `windfall`; the decisions live in `services/stances.py`, the writes
in `repositories/stances.py`, and the inbox screen at `/inbox`.

How each criterion is held:

- **Unacknowledged by default**: a stance is a row and its absence is the default — no row means
  nobody has looked yet, so a new Instrument needs no setup to be unacknowledged. The deliberate
  act is `PUT /api/instruments/{id}/stance`; `DELETE` returns a scope to unacknowledged.
- **Recorded but mints no lot**: recording is untouched, so the ledger still reconciles against
  the wallet. There is no lot engine yet (ticket 19); the rule it must read is
  `services/stances.inflow_mints_lot` — true only for `kept` — pinned by test next to the
  documented `no_lot_until_classified` consequence of `transfer_in`.
- **The inbox**: `GET /api/inbox` lists every (Instrument, Account) pair with an in-leg and no
  stance decision, with its pending unclassified inflows summarised. The numéraire is exempt —
  its movement is no disposal and it enters no cost basis. The UI offers exactly the three
  outcomes.
- **Scope**: the schema ties scope to stance — `(account_id IS NULL) = (stance = 'dangerous')` —
  so a mis-scoped decision cannot be stored; partial unique indexes hold each scope to one
  decision, and a global dangerous verdict outranks any per-Account row. A per-Account decision
  while the verdict stands is refused (409) rather than stored dead — and a keep would otherwise
  settle inflows under a stance that forbids it.
- **The counter-performance question**: keeping accepts
  `received_for_counter_performance` (default false) and, in the same database transaction,
  settles the pair's pending `transfer_in` inflows: yes → `airdrop` (§22 income at market
  value), no → `windfall`, a new type whose consequence — no income, no Anschaffung, per the
  BMF letter of 10.05.2022 — is documented in `services/tax_treatment.py` alone. Ignoring and
  condemning settle nothing.
- **Visible with a warning**: the instruments overview carries `dangerous` and the per-Account
  stances, and the Instruments screen wears an alarm `dangerous` / caution `ignored` chip beside
  the symbol; nothing is filtered out anywhere.
- **No price source**: price sources arrive with tickets 18/45, which must consult
  `services/stances.may_acquire_price_source` — false for dangerous, and false for ignored
  unless the same Instrument is kept at some other Account (dust at one venue must not unprice
  the genuine holding at another). Pinned by tests.

The seed keeps the holdings it mints and sprays one same-ticker token into the hot wallet,
left unacknowledged, so the development inbox demonstrates the flow; a seed re-run after the
inbox has been worked through respects the decisions. An e2e test drives keep-with-default-no
through the browser and rides on the seeded USD (EUR being exempt), skipping unseeded databases.
