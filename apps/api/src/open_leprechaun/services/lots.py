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
  (services/tax_treatment.Inflow) — a transfer in stays unclassified.

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
from decimal import Decimal

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
mints nothing."""


def derive(
    transaction_rows: list[Row],
    leg_rows: list[Row],
    *,
    numeraire_instruments: set[int],
    stance_rows: list[Row],
) -> list[Lot]:
    """Every lot the ledger supports, derived pure — the rows in, the lots
    out, nothing consulted beyond the arguments."""
    decisions_of: dict[int, list[Row]] = {}
    for row in stance_rows:
        decisions_of.setdefault(row.instrument_id, []).append(row)
    legs_of: dict[int, list[Row]] = {}
    for leg in leg_rows:
        legs_of.setdefault(leg.transaction_id, []).append(leg)
    minted = []
    for transaction in transaction_rows:
        inflow = TAX_CONSEQUENCES[transaction.type].inflow
        if inflow not in _BASIS_SOURCES:
            continue
        for leg in legs_of.get(transaction.id, []):
            if leg.role != "in" or leg.instrument_id in numeraire_instruments:
                continue
            stance = effective_stance(decisions_of.get(leg.instrument_id, ()), leg.account_id)
            if not inflow_mints_lot(stance):
                continue
            minted.append(
                Lot(
                    leg_id=leg.id,
                    account_id=leg.account_id,
                    instrument_id=leg.instrument_id,
                    acquired_at=transaction.occurred_at,
                    quantity=leg.quantity,
                    basis_eur=_basis_eur(
                        inflow, transaction, leg, legs_of[transaction.id], numeraire_instruments
                    ),
                    basis_source=_BASIS_SOURCES[inflow],
                )
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
    )
    lots.replace_all(connection, minted)
    fingerprints.record(connection, SUBJECT, fingerprint)


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
