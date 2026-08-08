"""Writes and reads over Instruments. Identity lives in the schema.

Each creator returns the new row's id, or None when that identity already
exists — the unique indexes are the arbiter, so a racing duplicate loses
cleanly. Decisions live in the service.
"""

from sqlalchemy import Connection, Engine, Row, text
from sqlalchemy.exc import IntegrityError


def create_crypto_token(
    engine: Engine, *, symbol: str, name: str, chain: str, contract_address: str
) -> int | None:
    """A crypto Instrument keyed on chain and contract address.

    Stored lowercased for display consistency; the unique index compares
    lowercased regardless, so checksum casing cannot mint a second identity.
    The contract opens the identifier history, as the ISIN does for a security.
    """
    try:
        with engine.begin() as connection:
            instrument_id = _insert_instrument(
                connection,
                family="crypto",
                type="token",
                symbol=symbol,
                name=name,
                chain=chain,
                contract_address=contract_address.lower(),
            )
            _insert_identifier(
                connection, instrument_id, kind="contract_address", value=contract_address.lower()
            )
            return instrument_id
    except IntegrityError:
        return None


def create_native_coin(engine: Engine, *, symbol: str, name: str, chain: str) -> int | None:
    """A chain's own coin: the symbol is the identity, and so it is also the
    identifier a later change would supersede in the history."""
    try:
        with engine.begin() as connection:
            instrument_id = _insert_instrument(
                connection, family="crypto", type="native", symbol=symbol, name=name, chain=chain
            )
            _insert_identifier(connection, instrument_id, kind="symbol", value=symbol)
            return instrument_id
    except IntegrityError:
        return None


def create_security(engine: Engine, *, symbol: str, name: str, type: str, isin: str) -> int | None:
    """A share, ETF, fund, bond or certificate, keyed on ISIN.

    The ISIN also opens the identifier history, in the same transaction, so
    every identifier a security ever had is findable in one place.
    """
    try:
        with engine.begin() as connection:
            instrument_id = _insert_instrument(
                connection, family="security", type=type, symbol=symbol, name=name, isin=isin
            )
            _insert_identifier(connection, instrument_id, kind="isin", value=isin)
            return instrument_id
    except IntegrityError:
        return None


def create_cash(engine: Engine, *, symbol: str, name: str) -> int | None:
    """A fiat currency, keyed on its code within the cash family."""
    return _create(engine, family="cash", type="fiat", symbol=symbol, name=name)


def add_listing(
    engine: Engine, instrument_id: int, *, venue: str, quote_currency: str
) -> int | None:
    """One market an Instrument trades on; what a price source points at."""
    try:
        with engine.begin() as connection:
            return connection.execute(
                text(
                    "INSERT INTO listing (instrument_id, venue, quote_currency)"
                    " VALUES (:instrument_id, :venue, :quote_currency) RETURNING id"
                ),
                {"instrument_id": instrument_id, "venue": venue, "quote_currency": quote_currency},
            ).scalar_one()
    except IntegrityError:
        return None


def list_listings(engine: Engine) -> list[Row]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT id, instrument_id, venue, quote_currency"
                    " FROM listing ORDER BY instrument_id, venue, quote_currency"
                )
            ).all()
        )


def list_instruments(engine: Engine) -> list[Row]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT id, family, type, symbol, name, chain, contract_address, isin"
                    " FROM instrument ORDER BY symbol, family, id"
                )
            ).all()
        )


def change_isin(engine: Engine, instrument_id: int, *, new_isin: str) -> bool:
    """Reassign a security's ISIN, as a merger or redomiciliation does.

    The old identifier is superseded in the history rather than forgotten, so
    anything recorded under it still resolves to this Instrument. False when
    the ISIN belongs to another Instrument, or this one is not a security.
    """
    try:
        with engine.begin() as connection:
            reassigned = connection.execute(
                text(
                    "UPDATE instrument SET isin = :new_isin"
                    " WHERE id = :instrument_id AND family = 'security'"
                ),
                {"instrument_id": instrument_id, "new_isin": new_isin},
            )
            if reassigned.rowcount != 1:
                return False
            connection.execute(
                text(
                    "UPDATE instrument_identifier SET superseded_at = now()"
                    " WHERE instrument_id = :instrument_id AND kind = 'isin'"
                    " AND superseded_at IS NULL"
                ),
                {"instrument_id": instrument_id},
            )
            _insert_identifier(connection, instrument_id, kind="isin", value=new_isin)
    except IntegrityError:
        return False
    return True


def add_identifier(engine: Engine, instrument_id: int, *, kind: str, value: str) -> None:
    """A lookup alias — WKN or ticker — for resolution, never for identity.

    The identity kinds are refused here: the current ISIN moves only through
    change_isin, so the history can never disagree with the identity column.
    """
    if kind not in ("wkn", "ticker"):
        raise ValueError(f"An alias is a wkn or a ticker, not {kind!r}.")
    with engine.begin() as connection:
        _insert_identifier(connection, instrument_id, kind=kind, value=value)


def find_by_identifier(engine: Engine, value: str) -> list[Row]:
    """Every Instrument the identifier has ever named — several is a normal
    answer, not an error, and the caller decides what to do with ambiguity."""
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT DISTINCT i.id, i.family, i.type, i.symbol, i.name,"
                    " i.chain, i.contract_address, i.isin"
                    " FROM instrument i"
                    " JOIN instrument_identifier x ON x.instrument_id = i.id"
                    " WHERE x.value = :value ORDER BY i.id"
                ),
                {"value": value},
            ).all()
        )


def _create(engine: Engine, **columns: str) -> int | None:
    try:
        with engine.begin() as connection:
            return _insert_instrument(connection, **columns)
    except IntegrityError:
        return None


def _insert_instrument(connection: Connection, **columns: str) -> int:
    return connection.execute(
        text(
            "INSERT INTO instrument (family, type, symbol, name, chain, contract_address, isin)"
            " VALUES (:family, :type, :symbol, :name, :chain, :contract_address, :isin)"
            " RETURNING id"
        ),
        {"chain": None, "contract_address": None, "isin": None, **columns},
    ).scalar_one()


def _insert_identifier(
    connection: Connection, instrument_id: int, *, kind: str, value: str
) -> None:
    # Changing back to a previously held identifier revives the old row
    # rather than violating the once-per-instrument constraint.
    connection.execute(
        text(
            "INSERT INTO instrument_identifier (instrument_id, kind, value)"
            " VALUES (:instrument_id, :kind, :value)"
            " ON CONFLICT ON CONSTRAINT instrument_identifier_once_per_instrument"
            " DO UPDATE SET superseded_at = NULL"
        ),
        {"instrument_id": instrument_id, "kind": kind, "value": value},
    )
