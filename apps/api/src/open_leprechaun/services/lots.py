"""The Tax Lot engine (ADR-0014). The transaction ledger is the only source
of truth: lots are derived in full, from the beginning of time, and stored
only so holdings (20) and the tax engines (21+) need not replay the ledger on
every request. Never patched incrementally — a rebuild swaps the whole table
inside one transaction that also stamps the per-class fingerprint of the
inputs it read, so two rebuilds over unchanged inputs produce identical rows
and a drifted table is detectable, and identified by input class.

What mints a lot — judged per in-leg at derivation time, so the answer always
reflects the stances and classifications of this moment:

- never the numéraire: every basis is expressed in it, so it has none of its
  own;
- only a leg whose (Instrument, Account) stance is `kept`
  (services/stances.inflow_mints_lot) — unacknowledged is deny by default,
  the failure mode an item waiting in the inbox rather than a holding
  silently valued at zero, and an ignored or dangerous position stays visible
  but never enters the cost basis;
- only a type whose documented consequence mints
  (services/tax_treatment.Inflow) — a transfer in stays unclassified;
- and the in-leg of a **confirmed self-transfer** (ticket 16), which mints
  what its matched out-leg consumed: the derivation replays each Account's
  FIFO queue, so a confirmed transfer carries the source lots across with
  their original acquisition instants, bases and basis sources — a
  self-transfer never restarts the Haltefrist, and a Depotübertrag preserves
  lot identity. What went missing en route — a network fee — comes off the
  head of the parcel, first in first out, so the destination never claims an
  older date than it can prove; what the source could not vouch for — an
  inflow no lot supports — carries nothing rather than inventing an
  acquisition. The confirmation is the Admin's classification, so the
  destination pair need not be separately kept — but a standing ignored or
  dangerous decision there still blocks the mint, as everywhere. Only
  confirmed links are inputs; an unmatched or rejected transfer changes no
  lot.

The basis is stated where the ledger alone can state it: a purchase against
the numéraire at its cost, an Opening Balance at its declared estimate, a
windfall at zero. A basis needing a rate or a market value is None until the
rate tickets (17, 18) extend the derivation — `basis_source` says which
valuation each lot awaits, and their tables are already declared input
classes, so their arrival marks the materialisation stale by itself.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal

from sqlalchemy import Connection, Engine, Row

from open_leprechaun.repositories import fingerprints, lots
from open_leprechaun.repositories.lots import Lot
from open_leprechaun.services.stances import effective_stance, inflow_mints_lot
from open_leprechaun.services.tax_treatment import TAX_CONSEQUENCES, Inflow

SUBJECT = "tax_lots"
"""The materialisation's name in the input_fingerprint table."""

_BASIS_SOURCES = {
    Inflow.mints_lot_at_cost: "cost",
    Inflow.income_at_market_value: "market_value",
    Inflow.mints_estimated_lot: "estimate",
    Inflow.no_acquisition: "without_consideration",
}
"""How each minting consequence determines its basis; an inflow absent here
mints nothing of its own — a matched transfer_in mints what it carries."""

_CENT = Decimal("0.01")
"""A pro-rated slice of a basis is stated in cents, the exact remainder
staying on the other part — no cent invented or lost by a split."""

_ROLE_ORDER = {"out": 0, "fee": 1, "in": 2}
"""Within one Transaction, what leaves is consumed before what arrives."""


@dataclass(frozen=True)
class _Slice:
    """A run of quantity in one Account's FIFO queue, wearing the acquisition
    it descends from — the unit a transfer carries across whole."""

    acquired_at: datetime
    quantity: Decimal
    basis_eur: Decimal | None
    basis_source: str


def derive(
    transaction_rows: list[Row],
    leg_rows: list[Row],
    *,
    numeraire_instruments: set[int],
    stance_rows: list[Row],
    match_rows: list[Row],
) -> list[Lot]:
    """Every lot the ledger supports, derived pure — the rows in, the lots
    out, nothing consulted beyond the arguments. One chronological pass over
    the ledger, keeping a FIFO queue of slices per (Account, Instrument):
    minting in-legs push, out and fee legs consume, and a confirmed match
    routes what its out-leg consumed to its in-leg's Account."""
    decisions_of: dict[int, list[Row]] = {}
    for row in stance_rows:
        decisions_of.setdefault(row.instrument_id, []).append(row)
    legs_of: dict[int, list[Row]] = {}
    for leg in leg_rows:
        legs_of.setdefault(leg.transaction_id, []).append(leg)
    leg_by_id = {leg.id: leg for leg in leg_rows}
    type_of = {transaction.id: transaction.type for transaction in transaction_rows}
    in_for_out = {match.out_leg_id: match.in_leg_id for match in match_rows}
    out_for_in = {match.in_leg_id: match.out_leg_id for match in match_rows}
    queues: dict[tuple[int, int], list[_Slice]] = {}
    arriving: dict[int, list[_Slice]] = {}
    consumed_out_legs: set[int] = set()
    minted = []
    for transaction in transaction_rows:
        siblings = legs_of.get(transaction.id, [])
        for leg in sorted(siblings, key=lambda leg: (_ROLE_ORDER[leg.role], leg.id)):
            if leg.instrument_id in numeraire_instruments:
                continue
            queue = queues.setdefault((leg.account_id, leg.instrument_id), [])
            if leg.role in ("out", "fee"):
                if leg.id in consumed_out_legs:
                    continue
                consumed = _consume(queue, leg.quantity)
                if (
                    leg.role == "out"
                    and transaction.type == "transfer_out"
                    and leg.id in in_for_out
                ):
                    arriving[in_for_out[leg.id]] = consumed
                continue
            if transaction.type == "transfer_in" and leg.id in out_for_in:
                if leg.id in arriving:
                    consumed = arriving.pop(leg.id)
                else:
                    consumed = _consume_at_source(
                        leg.id, out_for_in, leg_by_id, type_of, queues, consumed_out_legs
                    )
                minted.extend(_carry(leg, consumed, decisions_of, queue))
                continue
            inflow = TAX_CONSEQUENCES[transaction.type].inflow
            if inflow not in _BASIS_SOURCES:
                continue
            stance = effective_stance(decisions_of.get(leg.instrument_id, ()), leg.account_id)
            if not inflow_mints_lot(stance):
                continue
            basis = _basis_eur(inflow, transaction, leg, siblings, numeraire_instruments)
            minted.append(
                Lot(
                    leg_id=leg.id,
                    ordinal=0,
                    account_id=leg.account_id,
                    instrument_id=leg.instrument_id,
                    acquired_at=transaction.occurred_at,
                    quantity=leg.quantity,
                    basis_eur=basis,
                    basis_source=_BASIS_SOURCES[inflow],
                )
            )
            _enqueue(
                queue,
                [_Slice(transaction.occurred_at, leg.quantity, basis, _BASIS_SOURCES[inflow])],
            )
    return minted


def rebuild(engine: Engine) -> None:
    """Derive from the beginning of time and swap the table wholesale."""
    with _snapshot(engine) as connection:
        _rebuild_on(connection, fingerprints.current(connection))


@dataclass(frozen=True)
class DriftedInput:
    """One input class whose stored fingerprint no longer matches the current
    inputs. `stored_count` is None when no materialisation has ever run."""

    input_class: str
    stored_count: int | None
    current_count: int


def drift(engine: Engine) -> list[DriftedInput]:
    """What no longer matches, by input class — empty means the stored lots
    are authoritative."""
    with engine.connect() as connection:
        stored = fingerprints.stored(connection, SUBJECT)
        current = fingerprints.current(connection)
    drifted = [
        DriftedInput(
            input_class=input_class,
            stored_count=stored[input_class].row_count if input_class in stored else None,
            current_count=digest.row_count,
        )
        for input_class, digest in current.items()
        if stored.get(input_class) != digest
    ]
    # A class the registry no longer computes — a refactor, not data — still
    # means the stored lots rest on inputs nothing vouches for.
    drifted += [
        DriftedInput(
            input_class=input_class, stored_count=stored[input_class].row_count, current_count=0
        )
        for input_class in stored
        if input_class not in current
    ]
    return drifted


def fresh_lots(engine: Engine) -> list[Lot]:
    """The one way to read the materialisation: a persisted lot is
    authoritative only while its fingerprint matches (ADR-0014), so a drifted
    — or never-built — table is rebuilt before anything reads it. Check,
    rebuild and read share one snapshot: no ledger edit can slip between the
    check and the answer, and the fingerprint is computed once, not twice."""
    with _snapshot(engine) as connection:
        current = fingerprints.current(connection)
        if fingerprints.stored(connection, SUBJECT) != current:
            _rebuild_on(connection, current)
        return [
            Lot(
                leg_id=row.leg_id,
                ordinal=row.ordinal,
                account_id=row.account_id,
                instrument_id=row.instrument_id,
                acquired_at=row.acquired_at,
                quantity=row.quantity,
                basis_eur=row.basis_eur,
                basis_source=row.basis_source,
            )
            for row in lots.list_lots(connection)
        ]


@contextmanager
def _snapshot(engine: Engine) -> Iterator[Connection]:
    """One REPEATABLE READ transaction: every read — and a rebuild's stamp —
    describes the same instant of the ledger."""
    with (
        engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection,
        connection.begin(),
    ):
        yield connection


def _rebuild_on(connection: Connection, fingerprint: dict[str, fingerprints.InputDigest]) -> None:
    transaction_rows, leg_rows = lots.ledger(connection)
    minted = derive(
        transaction_rows,
        leg_rows,
        numeraire_instruments=lots.numeraire_instruments(connection),
        stance_rows=lots.stance_rows(connection),
        match_rows=lots.match_rows(connection),
    )
    lots.replace_all(connection, minted)
    fingerprints.record(connection, SUBJECT, fingerprint)


def _carry(
    leg: Row,
    consumed: list[_Slice],
    decisions_of: dict[int, list[Row]],
    queue: list[_Slice],
) -> list[Lot]:
    """The lots a confirmed transfer_in mints: what its out-leg consumed,
    trimmed to what actually arrived. The confirmation is the Admin's
    classification, so no separate keep is needed at the destination — but a
    standing ignored or dangerous decision there still blocks the mint, as it
    blocks every mint."""
    stance = effective_stance(decisions_of.get(leg.instrument_id, ()), leg.account_id)
    if stance in ("ignored", "dangerous"):
        return []
    slices = _arrived(consumed, leg.quantity)
    _enqueue(queue, slices)
    return [
        Lot(
            leg_id=leg.id,
            ordinal=ordinal,
            account_id=leg.account_id,
            instrument_id=leg.instrument_id,
            acquired_at=piece.acquired_at,
            quantity=piece.quantity,
            basis_eur=piece.basis_eur,
            basis_source=piece.basis_source,
        )
        for ordinal, piece in enumerate(slices)
    ]


def _consume_at_source(
    in_leg_id: int,
    out_for_in: dict[int, int],
    leg_by_id: dict[int, Row],
    type_of: dict[int, str],
    queues: dict[tuple[int, int], list[_Slice]],
    consumed_out_legs: set[int],
) -> list[_Slice]:
    """A deposit recorded before its withdrawal — venue clocks disagree —
    consumes the source queue now; the out-leg's own turn later is a no-op."""
    out_leg = leg_by_id[out_for_in[in_leg_id]]
    if out_leg.role != "out" or type_of[out_leg.transaction_id] != "transfer_out":
        return []
    consumed_out_legs.add(out_leg.id)
    source = queues.setdefault((out_leg.account_id, out_leg.instrument_id), [])
    return _consume(source, out_leg.quantity)


def _behead(slices: list[_Slice], quantity: Decimal) -> tuple[list[_Slice], list[_Slice]]:
    """Split a run of slices at a quantity boundary from the head, FIFO, the
    straddling slice divided pro-rata. Holding less than asked, everything is
    the head and the rest is empty."""
    head: list[_Slice] = []
    remaining = quantity
    for position, piece in enumerate(slices):
        if remaining == 0:
            return head, slices[position:]
        if piece.quantity <= remaining:
            head.append(piece)
            remaining -= piece.quantity
        else:
            first, rest = _split(piece, remaining)
            return [*head, first], [rest, *slices[position + 1 :]]
    return head, []


def _consume(queue: list[_Slice], quantity: Decimal) -> list[_Slice]:
    """Take quantity from the head of the queue. A queue holding less than
    asked — quantity no lot ever vouched for — yields only what it holds."""
    taken, rest = _behead(queue, quantity)
    queue[:] = rest
    return taken


def _arrived(consumed: list[_Slice], quantity: Decimal) -> list[_Slice]:
    """What the destination may claim of what left. The missing part — a
    network fee burnt en route — comes off the head, first in first out, so
    the oldest acquisition dates are surrendered before any is claimed."""
    excess = sum((piece.quantity for piece in consumed), Decimal(0)) - quantity
    if excess <= 0:
        return consumed
    _, kept = _behead(consumed, excess)
    return kept


def _split(piece: _Slice, first_quantity: Decimal) -> tuple[_Slice, _Slice]:
    """One slice in two, the basis pro-rata: the first part's share stated in
    cents, the exact remainder on the second — no cent invented or lost."""
    if piece.basis_eur is None:
        first_basis = rest_basis = None
    else:
        first_basis = (piece.basis_eur * first_quantity / piece.quantity).quantize(
            _CENT, ROUND_HALF_EVEN
        )
        rest_basis = piece.basis_eur - first_basis
    return (
        _Slice(piece.acquired_at, first_quantity, first_basis, piece.basis_source),
        _Slice(piece.acquired_at, piece.quantity - first_quantity, rest_basis, piece.basis_source),
    )


def _enqueue(queue: list[_Slice], slices: list[_Slice]) -> None:
    """Keep the queue in acquisition order — FIFO consumes the earliest
    Anschaffung first, and a carried slice may be older than what the
    destination already holds."""
    queue.extend(slices)
    queue.sort(key=lambda piece: piece.acquired_at)


def _basis_eur(
    inflow: Inflow,
    transaction: Row,
    leg: Row,
    siblings: list[Row],
    numeraire_instruments: set[int],
) -> Decimal | None:
    if inflow is Inflow.mints_estimated_lot:
        # An Opening Balance records exactly one position, so the header's
        # declared estimate names this leg's whole basis.
        return transaction.estimated_basis_eur
    if inflow is Inflow.no_acquisition:
        return Decimal(0)
    if inflow is Inflow.mints_lot_at_cost:
        return _eur_cost(leg, siblings, numeraire_instruments)
    # Income at market value on receipt — a price the ledger cannot state
    # until tickets 17/18.
    return None


def _eur_cost(leg: Row, siblings: list[Row], numeraire_instruments: set[int]) -> Decimal | None:
    """What the ledger alone can state a purchase cost: the legs that left
    plus the fees charged against this acquisition, when every one of them is
    the numéraire and this is the transaction's only acquisition. Anything
    else awaits a valuation (17, 18) — None, never a guess."""
    if sum(sibling.role == "in" for sibling in siblings) > 1:
        # Splitting one consideration across several positions needs their
        # relative market values.
        return None
    components = [
        sibling
        for sibling in siblings
        if sibling.role == "out"
        or (sibling.role == "fee" and sibling.charged_against_leg_id == leg.id)
    ]
    if any(component.instrument_id not in numeraire_instruments for component in components):
        return None
    return sum((component.quantity for component in components), Decimal(0))
