# 13 — Balanced-leg Transactions

**What to build:** The Admin can record any economic event by hand as a set of legs that balance — what left, what arrived, what a fee consumed — and can edit or delete it afterwards. A trade's other side is structural rather than conventional.

**Blocked by:** 10, 12

**Status:** done

- [x] A Transaction is a set of legs that balance; a buy records both the asset acquired and the cash spent
- [x] A fee is its own leg and is never double-counted
- [x] More than two legs are expressible, so a fee in a third asset is not a special case
- [x] The transaction vocabulary names what happened for both crypto and securities
- [x] Each transaction type's tax consequence is documented in one place, which the tax engines alone will read
- [x] An unclassified inflow is never assumed to be a purchase
- [x] Manual create, edit and delete work end to end from the UI
- [x] Monetary and quantity values are fixed-point decimals throughout, including in JSON

## Comments

Implemented. One revision (`75e168a8a7ca`) creates `transaction` and `transaction_leg`; the
structural rules live in `services/transactions.py`, and the tax-consequence document the tax
engines alone will read in `services/tax_treatment.py`.

How each criterion is held:

- **Legs that balance**: a leg's direction is its `role` — in, out or fee — never a sign
  convention (quantities are CHECKed positive). Which roles a type must and must not carry is
  one table in the service (`TRANSACTION_TYPES`), judged by `structural_defect` before anything
  is written, so a trade missing either side is refused with a sentence naming what is missing
  and an unbalanced event can never exist to be repaired later.
- **A fee is its own leg**: `role = 'fee'` is distinct from `out`, so no consumer can count it
  as the disposal side; it may attach to the sibling leg it was charged against
  (`charged_against_leg_id`), per ADR-0011's rule that a fee's tax treatment follows that leg's
  regime. A composite FK over `(charged_against_leg_id, transaction_id)` keeps the attachment
  inside the same Transaction and a CHECK keeps attachments to fee legs alone — both proven by
  raw-SQL tests.
- **More than two legs**: legs are rows, and the seed carries a trade of three legs whose fee is
  taken in a third Instrument. The API references a fee's target by position on the way in and
  answers with the stored leg's id.
- **Vocabulary**: trade, transfer in/out, spend, staking reward, lending interest, mining
  reward, airdrop, dividend, distribution, interest, fee — pinned by a CHECK in the schema, a
  `Literal` on the router and a zod enum on the client, held to each other by tests.
- **One tax-consequence document**: `services/tax_treatment.py` maps every type to what its
  in-legs and out-legs mean (lot at cost, income at market value, no lot until classified,
  disposal, awaiting match) with the statute where income applies. A test scans the package and
  fails if anything imports it; the tax engines (21, 22, 26) will amend that list with only
  themselves.
- **Inflow never a purchase**: `transfer_in` is documented as `no_lot_until_classified` —
  matching (16), an Opening Balance (15) or a Stance decision (14) settles what it was — and a
  test pins that it is not `mints_lot_at_cost`. Likewise `transfer_out` is `awaiting_match`,
  never quietly a disposal.
- **End to end from the UI**: `/transactions` (nav section "Ledger") lists the ledger newest
  first, with a multi-leg editor for create and edit and a two-press inline remove. A
  Playwright spec records, revises and removes a Transaction through the real browser against
  the real API.
- **Fixed-point throughout**: `NUMERIC` in Postgres, `Decimal` in Python, and **strings in
  JSON** — the API serialises quantities as plain decimal strings, the client's zod schema
  refuses a JSON number outright, and `formatQuantity` renders the string without ever passing
  through a float (a satoshi, an eighteen-decimal token unit and an integer beyond float
  precision are all round-tripped in tests).

Decisions worth recording:

- **`transaction` is the table name** — unreserved in Postgres, and the ubiquitous language
  wins over a hedge like `ledger_event`.
- **Deleting a Transaction cascades to its legs; an Account or Instrument with ledger entries
  refuses to go** (RESTRICT). The ledger is the only truth, so nothing it rests on may vanish
  from under it; the `db` test fixture and the seed respect the ordering.
- **Edit is wholesale replacement** (PUT): header updated and legs swapped in one database
  transaction. Lots are a later materialisation (19), so revision needs no compensation logic.
- **The repository discriminates FK failures by constraint name** ("no such Account" vs "no
  such Instrument" vs 404 on the Transaction itself), keeping the no-pre-check idiom from
  ticket 10.
- **The seed's ledger step rests only on the seed's own instruments** (USD, not the
  migration-minted EUR), so it holds on any database state; having no natural identity, each
  seeded event keys idempotency on `(type, occurred_at)` via `WHERE NOT EXISTS … RETURNING`.
- **Timestamps are absolute instants**: `timestamptz` in the schema, `AwareDatetime` on the
  API (a naive timestamp is a 422), local wall-time only in the browser's input control.
- No version bump — releases have not started; like tickets 10–12 this rides as `feat:` until
  one is cut.
- Post-review fixes (two-axis review): a quantity arriving as a **JSON number is refused with
  422** — it has been through, or is one parse away from, a binary float — where before it was
  accepted and silently rounded at the seventeenth significant digit; a second Playwright spec
  drives the ticket's headline shape (three legs, fee charged against one) through the browser's
  own controls; the two routes' validate-then-draft sequence collapsed into one `_balanced`
  helper; the decimal pattern is declared once (`DECIMAL_PATTERN`) and read by the zod schema,
  the form check and the input's own `pattern`; the ledger's instrument and account lookups are
  built once per table rather than per row; `docs/agents/design.md` § Numbers now names
  `formatQuantity` for fixed-point strings.
