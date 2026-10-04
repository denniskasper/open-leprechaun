# 38 — Address Indexer; Solana

**What to build:** The third ingestion mode, for a self-custody wallet that publishes neither an export nor an account — just a chain and an address. It is also the only mode that sees unsolicited inflows as they arrive.

**Blocked by:** 31, 10

**Status:** done

- [x] An Address Indexer port takes a chain and an address and returns normalized transfers
- [x] It requires no credentials and is read-only by nature rather than by permission
- [x] One chain ships working end to end through preview and commit
- [x] Inflows of unknown Instruments arrive as unacknowledged and mint no lots
- [x] The port is distinct from the exchange and connector ports and shares no assumptions with them
- [x] Tested against recorded fixtures

## Comments

Implemented as the port (`ports/address_indexer.py`), its registry (`ports/indexers.py`, served
through `adapters.get_address_indexers`), the seam into the import framework
(`services/address_imports.py`), a router generic over the registry
(`GET /address-indexers`, `POST /address-imports/preview`, `POST /address-imports`), the Solana
implementation (`ports/solana.py`), and a third flow on the Imports screen ("Read an address").
No migration.

How each criterion is held:

- **Chain and address in, normalized transfers out**: `history(address) -> AddressHistory` of
  Normalized Transfers, standalone Normalized Network Fees and warnings. A transfer names its
  asset by the chain's own identity (`ChainAsset`: the chain's coin, or a contract), in UTC and
  whole units.
- **No credentials, read-only by nature**: the port's one method takes the address and nothing
  else — there is no credential type to hand it. Solana calls three read methods of the public
  JSON-RPC, unsigned.
- **End to end through preview and commit**: the service turns transfers into the framework's
  rows and calls ticket 31's `evaluate`/`commit` — dedup, the authoritative source, the batch
  and its reversal are inherited. The source is `<chain>:<address>`, so the Account's one
  authoritative source names exactly which address feeds it; a second address previews but may
  not write.
- **Unknown Instruments arrive unacknowledged, minting no lot**: because the chain states
  identity, legs carry an identity spec rather than a resolved symbol; the framework creates
  what it has never seen, and Stance (ADR-0012) keeps it out of the lots until classified.
  A test pins the inbox entry and the empty lot table.
- **Distinct port**: it imports nothing from the exchange or connector ports and shares no
  type with them — no credentials, no file, no venue symbols.
- **Recorded fixtures**: `tests/fixtures/solana/recorded.json` is a recording of the public
  mainnet endpoint — a settled transaction, a failed one, a wallet's token accounts — trimmed
  to the fields an indexer reads, nothing altered. It is public chain state of strangers'
  addresses, not account-derived data. The indexer was also smoke-run live against the public
  endpoint.

How Solana is read:

- What moved is the difference between each transaction's own before-and-after balances —
  lamports per account, token balances per mint and owner — so no instruction is interpreted
  and any program is covered.
- A token sent into a wallet names the wallet's *token account*, never the wallet. The walk
  therefore covers the wallet and every token account it owns under both token programs, plus
  any since closed that the wallet's own history names. Without this the unsolicited token
  inflow is exactly what would be missed.
- SOL in the wallet's own token accounts (rent, wrapped SOL) counts as the wallet's SOL, and
  the wrapped-SOL mint is not also a token.
- The network fee is stated once, only when the address was the fee payer: on the outflow it
  enabled, or as a standalone `fee` Transaction when nothing else moved (a failed transaction).
- Rate limits: calls are spaced, a 429 waits as asked and retries a bounded number of times.
  What one finalized transaction moved is remembered in-process, so the commit after a preview
  re-asks only the signature lists.

Decisions worth recording:

- **Contract addresses keep their casing unless hex.** The token repository lowercased every
  contract; a base58 mint folded to lowercase names nothing on Solana (and could never be
  priced). Hex still folds; anything else is stored as given. Lookup and the unique index still
  compare case-insensitively.
- **Swaps arrive as transfers, with a warning. This is the indexer's main limit.** Balances
  state no intent: a transaction that moved one asset in and another out is flagged and counted,
  and the Admin replaces the pair with a trade. Pairing them automatically was left out — a swap
  routinely moves a third amount too (rent for a new token account), so the pair is not clean.
- **Staking is flagged, not modelled.** SOL delegated to a stake account leaves the address but
  not the owner, and rewards accrue in the stake account, which the walk does not read.
- **Token labels are not fetched from the chain.** A token's self-declared name is whatever its
  issuer typed — routinely a lure — so an unknown mint is labelled by its abbreviated address;
  two stablecoin mints carry the indexer's own label and peg.
- **The address is given per read, not read off the Account.** The Account's reference stays
  metadata (ticket 10); the screen only offers it as the starting value when the Account's
  chain matches.
- **A rent-funded SOL inflow can accompany an unsolicited token** — whoever opens the wallet's
  token account pays its rent into an account the wallet owns. That SOL is real and follows
  SOL's own Stance; only the unknown token waits in the inbox.
- **The RPC endpoint is a setting** (`SOLANA_RPC_URL`, default the public endpoint). The public
  one is slow for a long history: one call per transaction, and a walk refuses beyond twenty
  thousand transactions rather than truncate.
- **Not built: a scheduled read.** Reading is on demand. The authoritative source already names
  chain and address per Account, so a scheduled task could re-read them without new storage.
- **No Playwright journey**: one would need the live chain; the flow is covered at the API seam
  with the port's fake and by unit tests of the screen's wording.
- **Two-axis review folded in.** Token accounts since closed are now discovered and walked; a
  malformed answer anywhere surfaces as the port's `IndexerError`; the port declares
  `lookback_days` (ADR-0008's capability; Solana reads the whole history); the endpoint default
  lives in one place. Accepted as-is: the registry taking the endpoint as an argument (a second
  chain adds its own setting); identity comparing contracts case-insensitively (two base58
  mints differing only in case is not a practical collision); an old transaction that states no
  owner beside a token balance is judged by the token accounts known at read time, so a rare
  re-read after such an account closes could state its fee under a new identifier; and shapes
  shared with the CSV flow (the commit response mapping, the Account picker) left duplicated,
  as between the existing flows.
- No version bump — rides as `feat:` like the earlier tickets.
