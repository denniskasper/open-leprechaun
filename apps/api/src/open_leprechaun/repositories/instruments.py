"""Writes and reads over Instruments. Identity lives in the schema.

Each creator returns the new row's id, or None when that identity already
exists — the unique indexes are the arbiter, so a racing duplicate loses
cleanly. Decisions live in the service.
"""

from sqlalchemy import Connection, Engine, Row, text
from sqlalchemy.exc import IntegrityError

# The security types that are investment funds under §20 InvStG — the ones a
# Teilfreistellung classification belongs to.
FUND_TYPES = ("etf", "fund")

# The one shape an Instrument row is read in, wherever it is read.
_COLUMN_NAMES = (
    "id",
    "family",
    "type",
    "symbol",
    "name",
    "chain",
    "contract_address",
    "isin",
    "is_numeraire",
    "pegged_currency",
    "fund_category",
    "fund_category_source",
    "distribution_policy",
    "needs_review",
)
_COLUMNS = ", ".join(_COLUMN_NAMES)
_PREFIXED_COLUMNS = ", ".join(f"i.{name}" for name in _COLUMN_NAMES)


def create_crypto_token(
    engine: Engine,
    *,
    symbol: str,
    name: str,
    chain: str,
    contract_address: str,
    pegged_currency: str | None = None,
) -> int | None:
    """A crypto Instrument keyed on chain and contract address.

    Stored lowercased for display consistency; the unique index compares
    lowercased regardless, so checksum casing cannot mint a second identity.
    The contract opens the identifier history, as the ISIN does for a security.
    A stablecoin carries the currency it pegs, which routes its EUR value to
    the daily reference rate (ticket 17).
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
                pegged_currency=pegged_currency,
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


def create_security(
    engine: Engine,
    *,
    symbol: str,
    name: str,
    type: str,
    isin: str,
    wkn: str | None = None,
    ticker: str | None = None,
    venue: str | None = None,
    quote_currency: str | None = None,
    fund_category: str | None = None,
    fund_category_source: str | None = None,
    distribution_policy: str | None = None,
    needs_review: bool = False,
) -> int | None:
    """A share, ETF, fund, bond or certificate, keyed on ISIN.

    The ISIN also opens the identifier history, in the same transaction, so
    every identifier a security ever had is findable in one place. Everything
    a picked search candidate carries lands in the same stroke: WKN and
    ticker as lookup aliases, the primary listing, and — for a fund — the
    classification with its source. An import that met an unknown identifier
    creates flagged `needs_review`, which is the only state the schema admits
    type `unknown` in.
    """
    if (venue is None) != (quote_currency is None):
        raise ValueError("A Listing names its venue and quote currency together.")
    try:
        with engine.begin() as connection:
            instrument_id = connection.execute(
                text(
                    "INSERT INTO instrument (family, type, symbol, name, isin, fund_category,"
                    " fund_category_source, distribution_policy, needs_review)"
                    " VALUES ('security', :type, :symbol, :name, :isin, :fund_category,"
                    " :fund_category_source, :distribution_policy, :needs_review)"
                    " RETURNING id"
                ),
                {
                    "type": type,
                    "symbol": symbol,
                    "name": name,
                    "isin": isin,
                    "fund_category": fund_category,
                    "fund_category_source": fund_category_source,
                    "distribution_policy": distribution_policy,
                    "needs_review": needs_review,
                },
            ).scalar_one()
            _insert_identifier(connection, instrument_id, kind="isin", value=isin)
            if wkn is not None:
                _insert_identifier(connection, instrument_id, kind="wkn", value=wkn)
            if ticker is not None:
                _insert_identifier(connection, instrument_id, kind="ticker", value=ticker)
            if venue is not None and quote_currency is not None:
                # The picked candidate's primary listing is the market the
                # picker vouched for — it becomes the price source (ticket 45).
                connection.execute(
                    text(
                        "INSERT INTO listing (instrument_id, venue, quote_currency, price_source)"
                        " VALUES (:instrument_id, :venue, :quote_currency, true)"
                    ),
                    {
                        "instrument_id": instrument_id,
                        "venue": venue,
                        "quote_currency": quote_currency,
                    },
                )
            return instrument_id
    except IntegrityError:
        return None


def classify_fund(
    engine: Engine,
    instrument_id: int,
    *,
    category: str,
    source: str,
    distribution_policy: str | None,
) -> bool:
    """Record a fund's Teilfreistellung category with the source of the value
    — provider prefill or the Admin's own hand — and its distribution policy.

    False when the Instrument is missing or not a fund: the schema holds that
    classification belongs to funds alone, and this merely reports it.
    """
    try:
        with engine.begin() as connection:
            classified = connection.execute(
                text(
                    "UPDATE instrument SET fund_category = :category,"
                    " fund_category_source = :source, distribution_policy = :distribution_policy"
                    " WHERE id = :instrument_id AND family = 'security'"
                ),
                {
                    "instrument_id": instrument_id,
                    "category": category,
                    "source": source,
                    "distribution_policy": distribution_policy,
                },
            )
            return classified.rowcount == 1
    except IntegrityError:
        return False


def resolve_review(
    engine: Engine,
    instrument_id: int,
    *,
    type: str,
    symbol: str,
    name: str,
    fund_category: str | None = None,
    fund_category_source: str | None = None,
    distribution_policy: str | None = None,
) -> bool:
    """Settle an auto-created security: the Admin chooses its real type and
    display metadata — and, where the type makes it a fund, may classify it in
    the same act — and the review flag clears. Only a flagged security may be
    settled: this is the review's own act, never a general edit. A type that
    is not a fund's wipes any classification in the same stroke — a share
    carries none, and keeping a stale one would misstate its taxation.

    False when no flagged security carries the id, or the chosen type would
    leave it unsettled — the schema refuses `unknown` without the flag.
    """
    fund = type in FUND_TYPES
    try:
        with engine.begin() as connection:
            reviewed = connection.execute(
                text(
                    "UPDATE instrument SET type = :type, symbol = :symbol, name = :name,"
                    " needs_review = false,"
                    " fund_category = CASE WHEN :fund THEN"
                    "  COALESCE(:category, fund_category) ELSE NULL END,"
                    " fund_category_source = CASE WHEN :fund THEN"
                    "  COALESCE(:source, fund_category_source) ELSE NULL END,"
                    " distribution_policy = CASE WHEN :fund AND :category IS NOT NULL THEN"
                    "  :distribution_policy WHEN :fund THEN distribution_policy ELSE NULL END"
                    " WHERE id = :instrument_id AND family = 'security' AND needs_review"
                ),
                {
                    "instrument_id": instrument_id,
                    "type": type,
                    "symbol": symbol,
                    "name": name,
                    "fund": fund,
                    "category": fund_category,
                    "source": fund_category_source,
                    "distribution_policy": distribution_policy,
                },
            )
            return reviewed.rowcount == 1
    except IntegrityError:
        return False


def unclassified_funds(engine: Engine, *, through_year: int) -> list[Row]:
    """Every fund in the ledger up to the end of the Tax Year whose
    Teilfreistellung category nothing has stated, and every such security
    still typed `unknown` — which cannot yet say whether it is a fund, so
    nothing can say its exemption either. Bounded by holding, not by in-year
    trading: a fund bought earlier and merely held still accrues
    Vorabpauschale, so its missing classification still moves the year."""
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT DISTINCT i.id, i.symbol, i.name, i.type FROM instrument i"
                    " WHERE i.family = 'security' AND (i.type = 'unknown'"
                    "  OR (i.type IN ('etf', 'fund') AND i.fund_category IS NULL))"
                    " AND EXISTS (SELECT 1 FROM transaction_leg l"
                    "  JOIN transaction t ON t.id = l.transaction_id"
                    "  WHERE l.instrument_id = i.id"
                    "  AND extract(year FROM t.occurred_at AT TIME ZONE 'Europe/Berlin')"
                    "   <= :through_year)"
                    " ORDER BY i.symbol, i.id"
                ),
                {"through_year": through_year},
            ).all()
        )


def create_cash(engine: Engine, *, symbol: str, name: str) -> int | None:
    """A fiat currency, keyed on its code within the cash family.

    The code is cash's identity, so it opens the identifier history — as the
    symbol does for a native coin, and the ISIN for a security.
    """
    try:
        with engine.begin() as connection:
            instrument_id = _insert_instrument(
                connection, family="cash", type="fiat", symbol=symbol, name=name
            )
            _insert_identifier(connection, instrument_id, kind="symbol", value=symbol)
            return instrument_id
    except IntegrityError:
        return None


def wearing_symbol(engine: Engine, symbol: str, *, families: tuple[str, ...]) -> list[int]:
    """Every Instrument id wearing this symbol within the given families —
    the resolution-hint lookup a venue's bare symbol permits (ADR-0010). What
    more than one match means is the caller's judgement, never a pick."""
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT id FROM instrument"
                    " WHERE symbol = :symbol AND family = ANY(:families) ORDER BY id"
                ),
                {"symbol": symbol, "families": list(families)},
            ).scalars()
        )


def get(engine: Engine, instrument_id: int) -> Row | None:
    with engine.connect() as connection:
        return connection.execute(
            text(f"SELECT {_COLUMNS} FROM instrument WHERE id = :instrument_id"),
            {"instrument_id": instrument_id},
        ).one_or_none()


def numeraire(engine: Engine) -> Row | None:
    """The one Instrument whose movement is not a disposal (ADR-0011).

    EUR in this deployment — but that is a fact of the data, established by the
    migration chain and held to at most one row by the schema, not a constant
    anywhere in logic. None means no numéraire is designated, a state the
    migration chain never leaves behind on its own.
    """
    with engine.connect() as connection:
        return connection.execute(
            text(f"SELECT {_COLUMNS} FROM instrument WHERE is_numeraire")
        ).one_or_none()


def designate_numeraire(engine: Engine, instrument_id: int) -> bool:
    """Move the numéraire designation to another cash Instrument.

    In one transaction the current holder becomes an ordinary asset and the
    target takes the flag, so no moment leaves two numéraires for the schema
    to refuse. False when the target is missing or not cash, changing nothing.
    """
    with engine.begin() as connection:
        family = connection.execute(
            text("SELECT family FROM instrument WHERE id = :instrument_id"),
            {"instrument_id": instrument_id},
        ).scalar_one_or_none()
        if family != "cash":
            return False
        connection.execute(text("UPDATE instrument SET is_numeraire = false WHERE is_numeraire"))
        connection.execute(
            text("UPDATE instrument SET is_numeraire = true WHERE id = :instrument_id"),
            {"instrument_id": instrument_id},
        )
    return True


def add_listing(
    engine: Engine,
    instrument_id: int,
    *,
    venue: str,
    quote_currency: str,
    price_source: bool = False,
) -> int | None:
    """One market an Instrument trades on; what a price source points at.

    A listing arriving as the price source displaces the previous holder in
    the same transaction, so no moment holds two for the schema to refuse.
    The first Listing an Instrument gains takes the price source regardless —
    the rule is this repository's, not a client courtesy, so a bare security
    becomes priceable whoever the caller is (ADR-0021).
    """
    try:
        with engine.begin() as connection:
            if price_source:
                _clear_price_source(connection, instrument_id)
            return connection.execute(
                text(
                    "INSERT INTO listing (instrument_id, venue, quote_currency, price_source)"
                    " VALUES (:instrument_id, :venue, :quote_currency, :price_source"
                    "  OR NOT EXISTS (SELECT 1 FROM listing"
                    "   WHERE instrument_id = :instrument_id))"
                    " RETURNING id"
                ),
                {
                    "instrument_id": instrument_id,
                    "venue": venue,
                    "quote_currency": quote_currency,
                    "price_source": price_source,
                },
            ).scalar_one()
    except IntegrityError:
        return None


def set_price_source(engine: Engine, instrument_id: int, listing_id: int) -> bool:
    """Move the price source to a chosen Listing of the same Instrument.

    In one transaction the current holder loses the flag and the target takes
    it. False when the Listing is missing or belongs to another Instrument,
    changing nothing.
    """
    with engine.begin() as connection:
        owned = connection.execute(
            text("SELECT 1 FROM listing WHERE id = :listing_id AND instrument_id = :instrument_id"),
            {"listing_id": listing_id, "instrument_id": instrument_id},
        ).scalar_one_or_none()
        if owned is None:
            return False
        _clear_price_source(connection, instrument_id)
        connection.execute(
            text("UPDATE listing SET price_source = true WHERE id = :listing_id"),
            {"listing_id": listing_id},
        )
    return True


def _clear_price_source(connection: Connection, instrument_id: int) -> None:
    connection.execute(
        text("UPDATE listing SET price_source = false WHERE instrument_id = :instrument_id"),
        {"instrument_id": instrument_id},
    )


def list_listings(engine: Engine) -> list[Row]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT id, instrument_id, venue, quote_currency, price_source"
                    " FROM listing ORDER BY instrument_id, venue, quote_currency"
                )
            ).all()
        )


def list_instruments(engine: Engine) -> list[Row]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(f"SELECT {_COLUMNS} FROM instrument ORDER BY symbol, family, id")
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
                    f"SELECT DISTINCT {_PREFIXED_COLUMNS}"
                    " FROM instrument i"
                    " JOIN instrument_identifier x ON x.instrument_id = i.id"
                    " WHERE x.value = :value ORDER BY i.id"
                ),
                {"value": value},
            ).all()
        )


def _insert_instrument(connection: Connection, **columns: str | None) -> int:
    return connection.execute(
        text(
            "INSERT INTO instrument"
            " (family, type, symbol, name, chain, contract_address, isin, pegged_currency)"
            " VALUES (:family, :type, :symbol, :name, :chain, :contract_address, :isin,"
            " :pegged_currency)"
            " RETURNING id"
        ),
        {"chain": None, "contract_address": None, "isin": None, "pegged_currency": None, **columns},
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
