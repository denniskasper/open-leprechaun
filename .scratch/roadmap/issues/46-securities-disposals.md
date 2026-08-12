# 46 — Securities disposals

**What to build:** Share and fund sales are computed FIFO within the Depot that held them, with no holding-period exemption, and routed to the statutory category their instrument type demands.

**Blocked by:** 27, 43, 44

**Status:** done

- [x] FIFO within Depot and Instrument; holding period never exempts a securities gain
- [x] Gain is proceeds less cost basis less transaction costs, all in EUR at the rates of their respective event dates
- [x] Currency movement on the security is part of the gain, not a separate item
- [x] Fund gains are reduced by their partial exemption
- [x] Share gains route to the shares category; fund, bond and certificate gains to the other-income category
- [x] A partially consumed lot keeps its remaining basis proportionally
- [x] Each disposal emits a Section 20 Event and computes no tax itself
- [x] A transfer between the Admin's own Depots preserves lot identity and acquisition dates
- [x] Tests name the paragraph each rule implements

## Comments

Implemented as a producer beside the engine: `services/security_disposals.py` derives every
securities disposal from the ledger's single replay, and `section20.year_report` reduces each
one to a Section 20 Event — the producer states category and Teilfreistellung rate, the engine
alone exempts, nets, offsets and rates (ADR-0013).

How each criterion is held:

- **FIFO within Depot and Instrument**: the lot engine's queues are already per (Account,
  Instrument), and the producer reads the same single replay the §23 engine walks — the shared
  walk was extracted into `services/disposals.py` (replay, proceeds/costs valuation, pro-rata
  shares, shortfall refusal), so the two engines can never pair a disposal differently. No
  Haltefrist branch exists anywhere in the producer; a test sells after more than a year and
  asserts full taxability (§20 Abs. 4 Satz 7 EStG for FIFO; §23 Abs. 2 EStG for precedence).
- **Gain at the respective event dates' rates**: proceeds and the sale's own fees convert at
  the sale date, the basis at the acquisition date. A purchase paid in the numéraire keeps the
  basis the derivation stated; one paid in foreign cash is stated at report time from the
  purchase's own legs — `Slice` grew `minted_by_leg_id`, carried across transfers and splits,
  so the producer can reach the purchase transaction and value its cost components (out-legs
  plus attached fees, the same components `lots._eur_cost` reads) by the acquisition date's
  reference rate.
- **Currency movement inside the gain**: a consequence of the rule above — a test buys and
  sells a USD-listed share flat in USD across a rate move and asserts the drift lands in the
  securities gain (§20 Abs. 4 Satz 1 EStG).
- **Teilfreistellung**: five new required statutory rate keys
  (`partial_exemption_<fund_category>`, §20 InvStG), pinned into the vocabulary CHECK and
  seeded for 2024-2026 by migration `b6e19f4d3a57`; the fund's category (ticket 44) selects
  the disposal year's rate; the event carries the rate and the engine exempts gross before the
  pot — losses symmetrically (§21 InvStG, already the engine's rule).
- **Routing**: `share` → aktien (§20 Abs. 6 Satz 4 EStG); `etf`, `fund`, `bond`,
  `certificate` → sonstige. `unknown` is deliberately absent from the map and refuses.
- **Proportional partial consumption**: the lot engine's `_split` already pro-rates a
  straddled slice's basis in cents; tests assert both halves of a partially consumed lot.
- **One event, no tax**: the producer computes gains only; `section20.year_report` builds the
  events with empty withholding (ticket 47's) and the engine assesses.
- **Depot transfer**: already the lot engine's confirmed-match carry (ticket 16); a test moves
  shares between two broker Depots and asserts the sale consumes the original acquisition
  instant and basis (§43 Abs. 1 Satz 5 EStG).
- **Paragraph-named tests**: `tests/test_security_disposals.py`, each docstring citing its
  statute.

Decisions worth recording:

- **An unclassified fund or unknown-typed security refuses by name**
  (`UnclassifiedSecurityError`, HTTP 409 on report generation) rather than joining
  awaiting-valuation: both are Admin-fixable classification, like an unset statutory value —
  unlike a price nothing can state yet. The pre-flight blocker from ticket 44 still names them
  gently before finalisation.
- **A basis no rule can state waits**: splitting one consideration across several positions
  needs relative market values, and a securities lot minted by income at market value needs a
  security price — both leave the disposal awaiting valuation, blocking the year like an
  unvalued income leg, never guessed.
- **The shortfall enumeration generalised**: `disposals.lot_shortfalls` covers every
  lot-consuming family (crypto, cash, security), so the existing pre-flight blocker now names
  securities gaps too; the §23 module keeps only its regime rules.
- **The fingerprint's instruments class gained `fund_category`** — reclassifying a fund moves
  figures now, so it must mark dependent reports stale.
- The `tax_treatment` reader allowlist changed shape: §23 and the securities producer read
  disposal legs through `services/disposals`, which replaced `section23.py` in the list.
- Post-review fixes (two-axis review): the report-time pro-ration of a foreign-currency basis
  dropped its per-slice cents rounding — slices are valued independently there, so a rounded
  share could invent a cent across the halves of one lot, which exact division cannot; two
  tests close the coverage gaps the review named (the remaining half of a partially consumed
  lot, and a foreign-currency basis pro-rated over partial sales); `disposals.shares` was
  renamed `prorated` — in a securities codebase that name read as equity shares — and the
  thrice-repeated value-and-sum-legs loop collapsed into one `disposals.valued_sum`.
- No version bump — releases have not started; this rides as `feat:` like tickets 09-45.
