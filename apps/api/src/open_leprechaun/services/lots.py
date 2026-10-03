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

One acquisition has no in-leg: a coin-margined futures close (ticket 29)
settles its net result in the coin, so the closed positions of the futures
store — itself a source of truth, ADR-0009 — walk the derivation beside the
transactions and mint a settlement lot each (`_settlement`). Their tables
are declared input classes of this materialisation already, so a new fill
or manual position marks it stale like a ledger edit does.

And one event changes a holding with no leg at all: a **Corporate Action**
(ticket 52). The events walk the same pass in effect order and act on what is
open at that instant — the slices still in a queue, and those a confirmed
transfer has in transit — never on the ledger: a split rescales each slice's
quantity and leaves its basis and acquisition instant alone, a capital return
takes basis off, a merger moves every slice into the target Instrument and a
spin-off mints target slices carrying the share of basis the Admin supplied,
both under the original acquisition instant. A minted lot stays the
acquisition as its leg stated it; what an event did is read from the queues
(`Derivation.remaining`), from the quantity on the books (`Derivation.held`)
and, slice by slice, from `Derivation.effects` — the before and after a
preview shows. Nothing is stored, so removing the event and deriving again is
the whole of its reversal.
"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from sqlalchemy import Connection, Engine, Row

from open_leprechaun.repositories import corporate_actions, fingerprints, futures, lots
from open_leprechaun.repositories.lots import Lot
from open_leprechaun.services.futures import net_figure
from open_leprechaun.services.rounding import cents
from open_leprechaun.services.stances import (
    effective_stance,
    inflow_mints_lot,
    never_enters_cost_basis,
)
from open_leprechaun.services.tax_treatment import TAX_CONSEQUENCES, Inflow

SUBJECT = "tax_lots"
"""The materialisation's name in the input_fingerprint table."""

COST = "cost"
"""The basis_source of a purchase's lot. The derivation states the basis
where the ledger alone can (a numéraire consideration); one paid in anything
else stores None, and a disposal engine states it at report time from the
purchase's own legs — reached through the slice's minting leg (ticket 46)."""

ESTIMATE = "estimate"
"""The basis_source of an Opening Balance lot — the disposal engine (21)
flags every disposal consuming one as resting on an estimate."""

WITHOUT_CONSIDERATION = "without_consideration"
"""The basis_source of a kept windfall's lot — no Anschaffungsvorgang, so the
disposal engine (21) keeps its disposal out of §23."""

MARKET_VALUE = "market_value"
"""The basis_source of a lot minted by income (§22, ticket 22): the market
value on receipt — the same figure the income engine states, so income and
cost basis can never disagree. The derivation itself stores None until the
rate tickets (17, 18) extend it; the disposal engine (21) states the value by
the same rule at report time."""

_BASIS_SOURCES = {
    Inflow.mints_lot_at_cost: COST,
    Inflow.income_at_market_value: MARKET_VALUE,
    Inflow.mints_estimated_lot: ESTIMATE,
    Inflow.no_acquisition: WITHOUT_CONSIDERATION,
}
"""How each minting consequence determines its basis; an inflow absent here
mints nothing of its own — a matched transfer_in mints what it carries."""

_ROLE_ORDER = {"out": 0, "fee": 1, "in": 2}
"""Within one Transaction, what leaves is consumed before what arrives."""


def grouped(rows: list[Row], attribute: str) -> dict[int, list[Row]]:
    """Rows bucketed by one column, insertion-ordered — the index shape both
    the derivation and the disposal engine (21) walk the ledger through."""
    of: dict[int, list[Row]] = {}
    for row in rows:
        of.setdefault(getattr(row, attribute), []).append(row)
    return of


@dataclass(frozen=True)
class Slice:
    """A run of quantity in one Account's FIFO queue, wearing the acquisition
    it descends from — the unit a transfer carries across whole, and the unit
    a consuming leg is recorded as having consumed. `minted_by_leg_id` names
    the in-leg of that original acquisition, kept across transfers and splits,
    so a report-time engine can still reach the purchase that states a basis
    the derivation could not (ticket 46); None where no leg minted it — a
    futures settlement.

    A Corporate Action (ticket 52) rewrites the slice and leaves its trail in
    `changes`, oldest first, so a reader can still ask what the slice was
    before the event (`origin`). A basis the derivation could state is
    adjusted in `basis_eur` itself; one it could not carries the adjustment
    forward instead — `basis_share` of the basis at acquisition, less
    `basis_returned_eur` — for the engine that states it to apply
    (`restated`)."""

    acquired_at: datetime
    quantity: Decimal
    basis_eur: Decimal | None
    basis_source: str
    minted_by_leg_id: int | None = None
    changes: tuple[UnitChange, ...] = ()
    basis_share: Decimal = Decimal(1)
    basis_returned_eur: Decimal = Decimal(0)


@dataclass(frozen=True)
class UnitChange:
    """One Corporate Action's mark on a slice: at this instant, `units_old`
    of what it was became `units_new` of what it is. `from_instrument_id`
    names the Instrument it was units of before, where the event changed
    that — a merger or a spin-off — and `born` says the slice did not exist
    before the event at all: a spun-off slice inherits an acquisition instant
    but was never itself held earlier."""

    at: datetime
    units_new: Decimal
    units_old: Decimal
    from_instrument_id: int | None = None
    born: bool = False


@dataclass(frozen=True)
class LotState:
    """What one open lot holds at one moment. `basis_eur` is None while the
    basis awaits a valuation the derivation cannot state."""

    instrument_id: int
    quantity: Decimal
    basis_eur: Decimal | None


@dataclass(frozen=True)
class LotEffect:
    """What one Corporate Action did to one open lot: the lot before, and
    everything it became — two states where a spin-off left one part and
    moved another. `excess_eur` is what a capital return exceeded the lot's
    basis by: the basis stops at zero, and what the excess is taxed as is
    not the application's to assert."""

    account_id: int
    acquired_at: datetime
    basis_source: str
    before: LotState
    after: tuple[LotState, ...]
    excess_eur: Decimal = Decimal(0)


class CorporateAction(Protocol):
    """The event as the derivation reads it — a stored row or a proposed one
    (repositories/corporate_actions.CorporateAction), whose id is None."""

    @property
    def id(self) -> int | None: ...
    @property
    def kind(self) -> str: ...
    @property
    def instrument_id(self) -> int: ...
    @property
    def effective_at(self) -> datetime: ...
    @property
    def units_new(self) -> Decimal | None: ...
    @property
    def units_old(self) -> Decimal | None: ...
    @property
    def target_instrument_id(self) -> int | None: ...
    @property
    def basis_share(self) -> Decimal | None: ...
    @property
    def amount_per_unit_eur(self) -> Decimal | None: ...


@dataclass(frozen=True)
class Derivation:
    """One replay of the whole ledger: the lots it mints, what each consuming
    leg took from its queue — the pairing the disposal engine (ticket 21)
    reads — and what remains in each (Account, Instrument) queue at the end —
    the holdings view's cost basis (ticket 20). All derived in the same pass,
    so no two of them can disagree.

    `held` is what the books say sits where at the end: in-legs less out-
    and fee-legs per (Account, Instrument), what coin-margined closes settled
    (ticket 29), and what Corporate Actions made of both (ticket 52) — the
    quantity a queue is judged against, kept in the pass that keeps the
    queue. `effects` names, per Corporate Action id, what it did to each lot
    open at its instant; a proposed action answers under None."""

    lots: list[Lot]
    consumed: dict[int, list[Slice]]
    remaining: dict[tuple[int, int], list[Slice]]
    held: dict[tuple[int, int], Decimal]
    effects: dict[int | None, list[LotEffect]]


def derive(
    transaction_rows: list[Row],
    leg_rows: list[Row],
    *,
    numeraire_instruments: set[int],
    stance_rows: list[Row],
    match_rows: list[Row],
    futures_close_rows: Sequence[Row] = (),
    corporate_actions: Sequence[CorporateAction] = (),
) -> Derivation:
    """Everything the ledger supports, derived pure — the rows in, the lots
    and consumptions out, nothing consulted beyond the arguments. One
    chronological pass over the ledger, keeping a FIFO queue of slices per
    (Account, Instrument): minting in-legs push, out and fee legs consume,
    and a confirmed match routes what its out-leg consumed to its in-leg's
    Account.

    Closed futures positions walk the same pass in close order (ticket 29):
    a coin-margined close puts its settlement asset into the books, so a
    positive net figure mints a lot at the close — enqueued before any
    later disposal, consumed FIFO like every other acquisition.

    Corporate Actions walk it too (ticket 52), in effect order: each acts on
    what is open at its instant, before any transaction at that instant —
    a sale on the effective day is already stated in the new units."""
    decisions_of = grouped(stance_rows, "instrument_id")
    legs_of = grouped(leg_rows, "transaction_id")
    leg_by_id = {leg.id: leg for leg in leg_rows}
    type_of = {transaction.id: transaction.type for transaction in transaction_rows}
    in_for_out = {match.out_leg_id: match.in_leg_id for match in match_rows}
    out_for_in = {match.in_leg_id: match.out_leg_id for match in match_rows}
    queues: dict[tuple[int, int], list[Slice]] = {}
    arriving: dict[int, list[Slice]] = {}
    consumed_by_leg: dict[int, list[Slice]] = {}
    consumed_out_legs: set[int] = set()
    minted = []
    held: dict[tuple[int, int], Decimal] = {}
    effects: dict[int | None, list[LotEffect]] = {}
    # Closes and Corporate Actions in one order of time; the sort is stable,
    # so each keeps the order it was handed in within an instant, and a close
    # settles before an event of the same instant acts.
    legless = sorted(
        [(close.closed_at, False, close) for close in futures_close_rows]
        + [(action.effective_at, True, action) for action in corporate_actions],
        key=lambda event: event[:2],
    )
    walked = 0
    ordinals: dict[tuple[int, int, datetime], int] = {}

    def catch_up(instant: datetime | None) -> None:
        """Settle every close and apply every Corporate Action up to the
        instant — before the transaction at that instant, so a disposal at
        the closing timestamp can already consume what the close settled,
        and one on a split's effective day finds the rescaled queue."""
        nonlocal walked
        while walked < len(legless) and (instant is None or legless[walked][0] <= instant):
            _, is_action, event = legless[walked]
            if is_action:
                effects[event.id] = _apply(event, queues, arriving, leg_by_id, held, decisions_of)
            else:
                net = net_figure(event)
                if net > 0:
                    key = (event.account_id, event.settlement_instrument_id)
                    held[key] = held.get(key, Decimal(0)) + net
                minted.extend(
                    _settlement(event, decisions_of, numeraire_instruments, queues, ordinals)
                )
            walked += 1

    for transaction in transaction_rows:
        catch_up(transaction.occurred_at)
        siblings = legs_of.get(transaction.id, [])
        for leg in sorted(siblings, key=lambda leg: (_ROLE_ORDER[leg.role], leg.id)):
            key = (leg.account_id, leg.instrument_id)
            held[key] = held.get(key, Decimal(0)) + (
                leg.quantity if leg.role == "in" else -leg.quantity
            )
            if leg.instrument_id in numeraire_instruments:
                continue
            queue = queues.setdefault((leg.account_id, leg.instrument_id), [])
            if leg.role in ("out", "fee"):
                if leg.id in consumed_out_legs:
                    continue
                consumed = consumed_by_leg[leg.id] = _consume(queue, leg.quantity)
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
                    if out_for_in[leg.id] in consumed_out_legs:
                        consumed_by_leg[out_for_in[leg.id]] = consumed
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
                [
                    Slice(
                        transaction.occurred_at,
                        leg.quantity,
                        basis,
                        _BASIS_SOURCES[inflow],
                        minted_by_leg_id=leg.id,
                    )
                ],
            )
    catch_up(None)
    return Derivation(
        lots=minted, consumed=consumed_by_leg, remaining=queues, held=held, effects=effects
    )


def origin(piece: Slice, instrument_id: int) -> tuple[int, Decimal]:
    """What a slice of this Instrument was when it entered the books: the
    Instrument it was acquired as and how many units of it — every
    Corporate Action since undone. A report-time engine values a basis the
    derivation could not state from exactly this, at the acquisition's own
    instant."""
    quantity = piece.quantity
    for change in reversed(piece.changes):
        quantity = quantity * change.units_old / change.units_new
        if change.from_instrument_id is not None:
            instrument_id = change.from_instrument_id
    return instrument_id, quantity


def restated(piece: Slice, basis_at_acquisition: Decimal | None) -> Decimal | None:
    """The basis of a slice whose derivation stored none, once its engine
    has stated what the acquisition cost: the share Corporate Actions left
    with this slice, less what capital returns took off — never below zero,
    as a stated basis never is."""
    if basis_at_acquisition is None:
        return None
    return max(basis_at_acquisition * piece.basis_share - piece.basis_returned_eur, Decimal(0))


def rebuild(engine: Engine) -> None:
    """Derive from the beginning of time and swap the table wholesale."""
    with snapshot(engine) as connection:
        _rebuild_on(connection, fingerprints.current(connection))


def drift(engine: Engine) -> list[fingerprints.DriftedInput]:
    """What no longer matches, by input class — empty means the stored lots
    are authoritative. The comparison itself is the fingerprint module's
    (repositories/fingerprints.drifted), shared with the report lifecycle."""
    with engine.connect() as connection:
        stored = fingerprints.stored(connection, SUBJECT)
        current = fingerprints.current(connection)
    return fingerprints.drifted(stored, current)


def fresh_lots(engine: Engine) -> list[Lot]:
    """The one way to read the materialisation: a persisted lot is
    authoritative only while its fingerprint matches (ADR-0014), so a drifted
    — or never-built — table is rebuilt before anything reads it. Check,
    rebuild and read share one snapshot: no ledger edit can slip between the
    check and the answer, and the fingerprint is computed once, not twice."""
    with snapshot(engine) as connection:
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
def snapshot(engine: Engine) -> Iterator[Connection]:
    """One REPEATABLE READ transaction: every read — and a rebuild's stamp —
    describes the same instant of the ledger."""
    with (
        engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection,
        connection.begin(),
    ):
        yield connection


def derive_on(connection: Connection, *, proposed: Sequence[CorporateAction] = ()) -> Derivation:
    """The derivation of the ledger as this Connection's snapshot holds it —
    with Corporate Actions nobody has applied yet walked beside the stored
    ones, which is how a preview shows an event's effect without writing
    anything (ticket 52)."""
    transaction_rows, leg_rows = lots.ledger(connection)
    return derive(
        transaction_rows,
        leg_rows,
        numeraire_instruments=lots.numeraire_instruments(connection),
        stance_rows=lots.stance_rows(connection),
        match_rows=lots.match_rows(connection),
        futures_close_rows=futures.closed_position_rows(connection),
        corporate_actions=[*corporate_actions.action_rows(connection), *proposed],
    )


def _rebuild_on(connection: Connection, fingerprint: dict[str, fingerprints.InputDigest]) -> None:
    lots.replace_all(connection, derive_on(connection).lots)
    fingerprints.record(connection, SUBJECT, fingerprint)


def _apply(
    action: CorporateAction,
    queues: dict[tuple[int, int], list[Slice]],
    arriving: dict[int, list[Slice]],
    leg_by_id: dict[int, Row],
    held: dict[tuple[int, int], Decimal],
    decisions_of: dict[int, list[Row]],
) -> list[LotEffect]:
    """One Corporate Action, applied to every Account holding its Instrument
    at this point of the pass. Each open slice is rewritten by the kind's own
    rule (`_REWRITES`); the quantity on the books follows the slices, and
    whatever part of it no lot vouches for is rescaled by the same ratio —
    so the queue and the quantity it is judged against agree exactly, however
    a ratio rounds.

    What a merger or spin-off moves enters the target queue under the stance
    standing there: the event is the Admin's own record, so no separate keep
    is needed, but an ignored or dangerous target still enters no cost basis
    — as everywhere (ADR-0012).

    Slices a confirmed transfer has in transit are still held: a split
    rescales them and a capital return reaches them, so they arrive in the
    units their in-leg states. A merger or spin-off leaves them as they are —
    which Account its target units belong to in transit is exactly the kind
    of fact the application does not guess."""
    rewrite = _REWRITES[action.kind]
    effects = []
    accounts = sorted(
        {account_id for account_id, held_id in (*queues, *held) if held_id == action.instrument_id}
    )
    for account_id in accounts:
        key = (account_id, action.instrument_id)
        queue = queues.setdefault(key, [])
        unvouched = held.get(key, Decimal(0)) - _quantity(queue)
        outcomes = [(piece, rewrite(action, piece)) for piece in queue]
        staying = [outcome.stays for _, outcome in outcomes if outcome.stays is not None]
        moving = [outcome.moves for _, outcome in outcomes if outcome.moves is not None]
        queue[:] = staying
        if action.kind == "split":
            held[key] = _quantity(staying) + _rescaled(action, unvouched)
        entered = False
        if action.target_instrument_id is not None:
            target = (account_id, action.target_instrument_id)
            if action.kind == "merger":
                held[key] = Decimal(0)
            held[target] = (
                held.get(target, Decimal(0)) + _quantity(moving) + _rescaled(action, unvouched)
            )
            stance = effective_stance(decisions_of.get(action.target_instrument_id, ()), account_id)
            entered = not never_enters_cost_basis(stance)
            if entered:
                _enqueue(queues.setdefault(target, []), moving)
        effects += [
            _effect(action, account_id, piece, outcome, entered=entered)
            for piece, outcome in outcomes
        ]
    if action.target_instrument_id is None:
        for in_leg_id, pieces in arriving.items():
            in_leg = leg_by_id[in_leg_id]
            if in_leg.instrument_id != action.instrument_id:
                continue
            outcomes = [(piece, rewrite(action, piece)) for piece in pieces]
            pieces[:] = [outcome.stays for _, outcome in outcomes if outcome.stays is not None]
            effects += [
                _effect(action, in_leg.account_id, piece, outcome, entered=False)
                for piece, outcome in outcomes
            ]
    return effects


@dataclass(frozen=True)
class _Outcome:
    """What a Corporate Action made of one slice: the part staying in its
    queue, the part moving to the target Instrument's, and what a capital
    return exceeded the basis by."""

    stays: Slice | None = None
    moves: Slice | None = None
    excess_eur: Decimal = Decimal(0)


def _rescaled(action: CorporateAction, quantity: Decimal) -> Decimal:
    """A quantity through the event's ratio — multiplied before it is
    divided, so every ratio that comes out even is exact."""
    assert action.units_new is not None and action.units_old is not None
    return quantity * action.units_new / action.units_old


def _changed(action: CorporateAction, piece: Slice, **mark: int | bool) -> Slice:
    """The slice in its new units, the event added to its trail."""
    assert action.units_new is not None and action.units_old is not None
    change = UnitChange(action.effective_at, action.units_new, action.units_old, **mark)
    return replace(
        piece, quantity=_rescaled(action, piece.quantity), changes=(*piece.changes, change)
    )


def _split_units(action: CorporateAction, piece: Slice) -> _Outcome:
    """A split or reverse split: quantity by the ratio, per-unit basis
    therefore inversely — the total basis and the acquisition instant are
    not touched, and nothing taxable happened."""
    return _Outcome(stays=_changed(action, piece))


def _merge(action: CorporateAction, piece: Slice) -> _Outcome:
    """A merger: the slice becomes units of the target Instrument at the
    exchange ratio, carrying its whole basis and its acquisition instant."""
    return _Outcome(moves=_changed(action, piece, from_instrument_id=action.instrument_id))


def _spin_off(action: CorporateAction, piece: Slice) -> _Outcome:
    """A spin-off: the Admin's share of the basis leaves with new units of
    the target Instrument, under the original acquisition instant. A stated
    basis is divided in cents with the exact remainder staying behind, so no
    cent is invented or lost; an awaited one divides when it is stated."""
    assert action.basis_share is not None
    spun = _changed(action, piece, from_instrument_id=action.instrument_id, born=True)
    moved_returned = cents(piece.basis_returned_eur * action.basis_share)
    if piece.basis_eur is None:
        moved_share = piece.basis_share * action.basis_share
        return _Outcome(
            stays=replace(
                piece,
                basis_share=piece.basis_share - moved_share,
                basis_returned_eur=piece.basis_returned_eur - moved_returned,
            ),
            moves=replace(spun, basis_share=moved_share, basis_returned_eur=moved_returned),
        )
    moved_basis = cents(piece.basis_eur * action.basis_share)
    return _Outcome(
        stays=replace(piece, basis_eur=piece.basis_eur - moved_basis),
        moves=replace(spun, basis_eur=moved_basis),
    )


def _return_capital(action: CorporateAction, piece: Slice) -> _Outcome:
    """A capital return: the amount per unit comes off the slice's basis
    rather than counting as income. A stated basis stops at zero and the
    excess is named, never taxed here; an awaited one remembers what to take
    off when it is stated."""
    assert action.amount_per_unit_eur is not None
    returned = cents(piece.quantity * action.amount_per_unit_eur)
    if piece.basis_eur is None:
        return _Outcome(
            stays=replace(piece, basis_returned_eur=piece.basis_returned_eur + returned)
        )
    return _Outcome(
        stays=replace(piece, basis_eur=max(piece.basis_eur - returned, Decimal(0))),
        excess_eur=max(returned - piece.basis_eur, Decimal(0)),
    )


_REWRITES = {
    "split": _split_units,
    "merger": _merge,
    "spin_off": _spin_off,
    "capital_return": _return_capital,
}
"""Each kind's rule for one open slice."""


def _effect(
    action: CorporateAction, account_id: int, piece: Slice, outcome: _Outcome, *, entered: bool
) -> LotEffect:
    after = []
    if outcome.stays is not None:
        after.append(
            LotState(action.instrument_id, outcome.stays.quantity, outcome.stays.basis_eur)
        )
    if outcome.moves is not None and entered:
        assert action.target_instrument_id is not None
        after.append(
            LotState(action.target_instrument_id, outcome.moves.quantity, outcome.moves.basis_eur)
        )
    return LotEffect(
        account_id=account_id,
        acquired_at=piece.acquired_at,
        basis_source=piece.basis_source,
        before=LotState(action.instrument_id, piece.quantity, piece.basis_eur),
        after=tuple(after),
        excess_eur=outcome.excess_eur,
    )


def _quantity(slices: list[Slice]) -> Decimal:
    return sum((piece.quantity for piece in slices), Decimal(0))


def _settlement(
    close: Row,
    decisions_of: dict[int, list[Row]],
    numeraire_instruments: set[int],
    queues: dict[tuple[int, int], list[Slice]],
    ordinals: dict[tuple[int, int, datetime], int],
) -> list[Lot]:
    """The lot a settled close mints (ticket 29): the position's net figure
    (services/futures.net_figure) of the settlement Instrument, acquired at
    the close, at market value there. The basis is stated at report time by
    the same rule, and at the same instant, that values the position's
    Section 20 Event (ticket 28), so income and cost basis can never
    disagree. The rule is variant-agnostic on purpose: the coin-margined
    close is the motivating case, but a linear contract's profit in a
    stablecoin or foreign cash is the same acquisition — an asset entered
    the books at the close, whatever formula produced its amount.

    The numéraire settles no lot — every basis is expressed in it. An
    ignored or dangerous settlement Instrument never enters the cost basis,
    as everywhere (ADR-0012); an unacknowledged one mints regardless — the
    settlement asset is no unsolicited arrival awaiting classification but
    the denomination of the Admin's own contract, and its result already
    counts as capital income whatever the stance. A losing close mints
    nothing: what the loss took from the margin is reconciliation's to
    surface (ticket 39), not an acquisition's."""
    if close.settlement_instrument_id in numeraire_instruments:
        return []
    net = net_figure(close)
    if net <= 0:
        return []
    stance = effective_stance(
        decisions_of.get(close.settlement_instrument_id, ()), close.account_id
    )
    if never_enters_cost_basis(stance):
        return []
    key = (close.account_id, close.settlement_instrument_id)
    ordinal = ordinals.get((*key, close.closed_at), 0)
    ordinals[(*key, close.closed_at)] = ordinal + 1
    _enqueue(queues.setdefault(key, []), [Slice(close.closed_at, net, None, MARKET_VALUE)])
    return [
        Lot(
            leg_id=None,
            ordinal=ordinal,
            account_id=close.account_id,
            instrument_id=close.settlement_instrument_id,
            acquired_at=close.closed_at,
            quantity=net,
            basis_eur=None,
            basis_source=MARKET_VALUE,
        )
    ]


def _carry(
    leg: Row,
    consumed: list[Slice],
    decisions_of: dict[int, list[Row]],
    queue: list[Slice],
) -> list[Lot]:
    """The lots a confirmed transfer_in mints: what its out-leg consumed,
    trimmed to what actually arrived. The confirmation is the Admin's
    classification, so no separate keep is needed at the destination — but a
    standing ignored or dangerous decision there still blocks the mint, as it
    blocks every mint."""
    stance = effective_stance(decisions_of.get(leg.instrument_id, ()), leg.account_id)
    if never_enters_cost_basis(stance):
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
    queues: dict[tuple[int, int], list[Slice]],
    consumed_out_legs: set[int],
) -> list[Slice]:
    """A deposit recorded before its withdrawal — venue clocks disagree —
    consumes the source queue now; the out-leg's own turn later is a no-op."""
    out_leg = leg_by_id[out_for_in[in_leg_id]]
    if out_leg.role != "out" or type_of[out_leg.transaction_id] != "transfer_out":
        return []
    consumed_out_legs.add(out_leg.id)
    source = queues.setdefault((out_leg.account_id, out_leg.instrument_id), [])
    return _consume(source, out_leg.quantity)


def _behead(slices: list[Slice], quantity: Decimal) -> tuple[list[Slice], list[Slice]]:
    """Split a run of slices at a quantity boundary from the head, FIFO, the
    straddling slice divided pro-rata. Holding less than asked, everything is
    the head and the rest is empty."""
    head: list[Slice] = []
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


def _consume(queue: list[Slice], quantity: Decimal) -> list[Slice]:
    """Take quantity from the head of the queue. A queue holding less than
    asked — quantity no lot ever vouched for — yields only what it holds."""
    taken, rest = _behead(queue, quantity)
    queue[:] = rest
    return taken


def _arrived(consumed: list[Slice], quantity: Decimal) -> list[Slice]:
    """What the destination may claim of what left. The missing part — a
    network fee burnt en route — comes off the head, first in first out, so
    the oldest acquisition dates are surrendered before any is claimed."""
    excess = sum((piece.quantity for piece in consumed), Decimal(0)) - quantity
    if excess <= 0:
        return consumed
    _, kept = _behead(consumed, excess)
    return kept


def _split(piece: Slice, first_quantity: Decimal) -> tuple[Slice, Slice]:
    """One slice in two, the basis pro-rata: the first part's share stated in
    cents (services/rounding), the exact remainder on the second — no cent
    invented or lost."""
    if piece.basis_eur is None:
        first_basis = rest_basis = None
    else:
        first_basis = cents(piece.basis_eur * first_quantity / piece.quantity)
        rest_basis = piece.basis_eur - first_basis
    # What capital returns took off an awaited basis divides the same way.
    first_returned = cents(piece.basis_returned_eur * first_quantity / piece.quantity)
    return (
        replace(
            piece,
            quantity=first_quantity,
            basis_eur=first_basis,
            basis_returned_eur=first_returned,
        ),
        replace(
            piece,
            quantity=piece.quantity - first_quantity,
            basis_eur=rest_basis,
            basis_returned_eur=piece.basis_returned_eur - first_returned,
        ),
    )


def _enqueue(queue: list[Slice], slices: list[Slice]) -> None:
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
