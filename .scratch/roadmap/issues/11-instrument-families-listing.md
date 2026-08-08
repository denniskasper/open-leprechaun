# 11 — Instrument, families, Listing

**What to build:** One **Instrument** concept covering every tradable thing, with family-specific attributes. Crypto Instruments are keyed on chain and contract so two tokens sharing a ticker can never collapse into one row.

**Blocked by:** 03

**Status:** ready-for-agent

- [x] `family` distinguishes crypto, security and cash; `type` refines it
- [x] A crypto Instrument with a contract is keyed on chain and contract address; native coins key on symbol
- [x] A symbol is a display label and a resolution hint, never authoritative for identity
- [x] A **Listing** — Instrument, venue, quote currency — is its own concept, and price sources point at it
- [x] Each Instrument keeps an identifier history so a later identifier change does not orphan anything referring to it
- [x] Two Instruments sharing a symbol can coexist and are distinguishable in the UI

## Comments

Implemented. One revision creates `instrument`, `listing` and `instrument_identifier`; identity
is the schema's job, not a repository courtesy — the repository
(`repositories/instruments.py`) merely reports a lost race as `None`.

How each criterion is held:

- **Family and type**: CHECK constraints pin `family` to crypto/security/cash and `type` to the
  types each family admits (native/token; share/etf/fund/bond/certificate; fiat), plus per-family
  key checks (crypto carries chain, token also contract; only securities carry ISIN).
- **Crypto keying**: a partial unique index on `(chain, lower(contract_address))` keys tokens —
  lowercased in the index itself, so no write path can mint a second identity through checksum
  casing (a raw-SQL test proves the schema alone refuses it). Native coins key on symbol within
  their family slice; cash on symbol within its own. Securities key on ISIN.
- **Symbol never authoritative**: symbol appears in no token index, and two tokens sharing a
  ticker — the v1 collision case — are just two rows.
- **Listing**: `(instrument, venue, quote_currency)` unique; the table exists so the price-source
  tickets (18/45) have a target that names market and currency.
- **Identifier history**: every Instrument opens its history at creation — a security's ISIN, a
  token's contract, a native coin's symbol — so a later change supersedes a row rather than
  orphaning references (which all use the surrogate id). `change_isin` supersedes and re-keys in
  one transaction; `find_by_identifier` resolves superseded values and returns *candidates*,
  because "I don't know which of these you mean" is a normal answer (ADR-0010). WKN/ticker are
  alias kinds only, and the alias door refuses identity kinds so history and the identity column
  cannot disagree.
- **UI**: an Instruments page (`/instruments`, nav section "Ledger") lists symbol, name,
  family · type, identity and listings. Symbol is a label; the identity column (chain ·
  abbreviated contract, chain · native, ISIN, or currency code) does the distinguishing, and a
  symbol displayed by more than one row wears a caution-toned "shared" microlabel. Verified in
  the running app against the seed.

Decisions worth recording:

- **`GET /api/instruments` is the whole API surface.** Creation stays at the repository seam —
  imports (31/40), security search (44) and cash (12) own the creation flows, and inventing a
  create endpoint here would have prejudged their UX. The route takes `AdminDep`, satisfying the
  every-non-public-route test.
- **`create_cash` exists but nothing calls it yet**: criterion 1 requires the cash family to be
  real (schema slot, identity index, a test that all three families coexist); EUR, the numéraire
  and all cash semantics remain ticket 12's.
- **The seed** adds the collision pair (two `UNI` tokens on different chains), two native coins
  and one security with a listing and aliases, idempotent via bare `ON CONFLICT DO NOTHING` so
  the identity indexes decide what already exists.
- Post-review fixes (two-axis review): the token index moved to `lower(contract_address)`; the
  identifier history was widened from securities-only to every family; `add_identifier` gained
  the alias-kind guard; mono table cells gained `tabular-nums` per the design foundation.
