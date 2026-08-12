# 10 — Platform and Account

**What to build:** The Admin can register the places that hold value and the holdings under them. A **Platform** is any such place, distinguished by kind; an **Account** is one holding under exactly one Platform, and it is the boundary for FIFO lot matching.

**Blocked by:** 03, 07, 02

**Status:** done

- [x] Platform kinds cover exchange, cold storage, software wallet, broker and bank
- [x] Every Account belongs to exactly one Platform; none is locationless
- [x] Settings groups Platforms by kind
- [x] An Account records an address, reference or identifier as metadata only, never as a data source
- [x] An Account records extra software required to reach it, surfaced later on the holding
- [x] An Account can be scoped as finely as its Platform evidences — the model permits several Accounts per Platform and per chain
- [x] The vocabulary in code, API and UI is Platform and Account; "Exchange" appears only for the exchange kind

## Comments

Implemented. One revision creates `platform` and `account`; as with ticket 11, identity and the
rules are the schema's job and the repository (`repositories/platforms.py`) only reports what the
constraints decided.

How each criterion is held:

- **The five kinds**: a CHECK constraint pins `kind` to exchange/cold_storage/software_wallet/
  broker/bank, mirrored by a `Literal` on the request model and a zod enum on the client, so a
  sixth kind is refused at the database, at the API and in the browser. A raw-SQL test proves the
  schema alone refuses one.
- **Nothing locationless**: `account.platform_id` is NOT NULL with a foreign key, tested by
  inserting a NULL directly. The key is `ON DELETE RESTRICT`, not CASCADE — an Account is a FIFO
  boundary with holdings behind it, so removing the place it sits under is refused rather than
  quietly taking the holdings along.
- **Grouped by kind**: `/settings/platforms` (nav section "Settings") lists Platforms under their
  kind in canonical order, empty kinds omitted, each group naming how many it holds.
- **Reference as metadata only**: `external_reference` holds an address, IBAN or venue reference.
  Nothing reads it — no code path treats it as a source — and the UI says so on hover.
- **Access software**: `access_software` records what is needed to reach the holding; ticket 20
  surfaces it on the holding itself.
- **Evidence-scoped**: Accounts are unique on `(platform_id, name)` and deliberately **not** on
  chain, so one device yields as many Accounts as its export evidences. The seed carries a
  cold-storage device with two Accounts on the same chain, and a test asserts that shape.
- **Vocabulary**: Platform and Account throughout code, API and UI. "Exchange" appears only as
  the name of its own kind, held there by a test over the whole vocabulary map.

Decisions worth recording:

- **A Platform name is unique within its kind, not globally.** One brand may be a bank and a
  broker both, and those are two places that hold value; a global unique on name would have made
  the second unregisterable.
- **Depot is UI copy, not a schema entity.** Per CONTEXT.md, an Account under a broker Platform is
  what the Admin and the broker both call a Depot, so the broker rows say "Add Depot" and
  "2 Depots" while the model, the API and every other kind stay Platform and Account. Withholding
  behaviour and the Freistellungsauftrag remain ticket 43's.
- **The insert is the existence check.** `create_account` reads *which* constraint failed from the
  error rather than pre-checking the Platform: a foreign-key violation answers 404 "No such
  Platform" and a unique violation 409 "already exists", so the two are never conflated and there
  is no check-then-insert race.
- **`GET /api/platforms` nests Accounts under their Platform**, because an Account never means
  anything without its location. Creation is two POSTs, both behind `AdminDep`. Managed/synced
  Accounts (spec story 25) belong to ticket 34, which owns Connections; custody type on holdings
  (story 28) belongs to ticket 20.
- Post-review fixes (two-axis review): name unique per kind rather than globally; CASCADE became
  RESTRICT; the duplicate-vs-missing conflation and its TOCTOU pre-check removed; `kind` typed on
  the response model rather than bare `str`; names trimmed before they are judged, so whitespace
  cannot become a name; the two kind-label maps merged into one vocabulary map; the shared
  `postJson`/`refusal` client helpers moved out of `api/auth.ts` into `api/http.ts` so adding a
  screen no longer edits auth.
