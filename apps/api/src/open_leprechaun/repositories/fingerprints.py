"""The input fingerprint (ADR-0014): counts and digests per input class,
computed inside Postgres so a staleness check never hauls the ledger into
Python. A materialisation stamps the fingerprint of the inputs that produced
it under its subject; a subject whose stored rows no longer match the current
computation is detectably stale rather than quietly wrong. Reports (ticket 23)
reuse the same table and classes under their own subject — the mechanism is
deliberately shared, never duplicated.

Each class digests exactly the columns a derivation reads, so a note edit
never churns a materialisation while every tax-relevant change does. A class
declared with no source — rates, corporate actions (52) — digests as empty,
whether its table is unbuilt or deliberately excluded (each entry says
which); the ticket that points an entry at rows makes that first real digest
mark every dependent materialisation stale. An empty table digests like an
absent one, so the pointing itself drifts nothing.

These functions take the caller's Connection, not the Engine: a rebuild must
stamp the fingerprint inside the same transaction — and snapshot — that read
the inputs, or the stamp could describe a ledger the derivation never saw.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256

from sqlalchemy import Connection, text

NOTHING = sha256(b"").hexdigest()
"""What zero rows digest to — also the standing digest of a declared class
whose table no ticket has built yet."""


def _line(*columns: str) -> str:
    """One row as one text line: fields joined by a unit separator, NULL as a
    record separator — so no two different rows can serialise alike."""
    fields = ", ".join(f"coalesce(({column})::text, chr(30))" for column in columns)
    return f"concat_ws(chr(31), {fields})"


def _utc(column: str) -> str:
    """An absolute instant rendered independently of the session timezone,
    which would otherwise leak into the digest."""
    return f"to_char({column} AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS.US')"


INPUT_CLASSES: Mapping[str, str | None] = {
    # The ledger itself: the header's tax-relevant declarations, never the
    # note — prose for the Admin churns no materialisation.
    "transactions": (
        f"SELECT {_line('id', 'type', _utc('occurred_at'), 'reconstructed', 'estimated_basis_eur')}"
        " AS line FROM transaction"
    ),
    "transaction_legs": (
        "SELECT "
        + _line(
            "id",
            "transaction_id",
            "account_id",
            "instrument_id",
            "role",
            "quantity",
            "charged_against_leg_id",
        )
        + " AS line FROM transaction_leg"
    ),
    # The classification, not the display label: family and type decide a tax
    # regime, the numéraire designation decides what mints at all, and the
    # fund category which Teilfreistellung a securities disposal carries
    # (ticket 46) — reclassifying a fund must mark dependent reports stale.
    "instruments": (
        f"SELECT {_line('id', 'family', 'type', 'is_numeraire', 'fund_category')}"
        " AS line FROM instrument"
    ),
    "stances": (
        f"SELECT {_line('instrument_id', 'account_id', 'stance')} AS line FROM instrument_stance"
    ),
    # The Admin's confirmed self-transfer links (ticket 16): which out-leg
    # carries its lots to which in-leg. Only confirmed links reach the
    # derivation — a rejection changes proposals, never lots.
    "transfer_matches": (
        f"SELECT {_line('out_leg_id', 'in_leg_id')} AS line"
        " FROM transfer_match WHERE verdict = 'confirmed'"
    ),
    # Statutory values per year (ticket 09) — correcting a rate changes every
    # figure resting on it while no transaction has moved (ADR-0014). The
    # cited source is prose, like a note.
    "statutory_configuration": (
        f"SELECT {_line('year', 'key', 'value')} AS line FROM statutory_value"
    ),
    # The Admin's standing elections, which select the statutory values that
    # apply.
    "tax_election": f"SELECT {_line('filing_status', 'church_tax')} AS line FROM tax_election",
    # Futures (ticket 28, ADR-0009): the immutable fills and funding
    # payments, and the Admin's own manual positions. Derived positions are
    # a pure function of the fills and funding attribution a pure function
    # of positions and payments, so neither is fingerprinted itself — the
    # inputs vouch for both.
    "futures_fills": (
        "SELECT "
        + _line(
            "id",
            "source",
            "external_id",
            "account_id",
            "symbol",
            "side",
            "price",
            "size",
            "fee",
            "settlement_instrument_id",
            _utc("occurred_at"),
            "position_side",
            "reduce_only",
            "realized",
            "inverse",
        )
        + " AS line FROM futures_fill"
    ),
    "funding_payments": (
        "SELECT "
        + _line(
            "id",
            "source",
            "external_id",
            "account_id",
            "symbol",
            "amount",
            "settlement_instrument_id",
            _utc("occurred_at"),
            "position_side",
        )
        + " AS line FROM funding_payment"
    ),
    "manual_futures_positions": (
        "SELECT "
        + _line(
            "id",
            "account_id",
            "symbol",
            "side",
            "quantity",
            "settlement_instrument_id",
            _utc("opened_at"),
            _utc("closed_at"),
            "realized",
            "fees",
        )
        + " AS line FROM futures_position WHERE origin = 'manual'"
    ),
    # Deliberately empty although the reference-rate store (17) exists: that
    # store is append-only and immutable (ADR-0017) — a fetch only ever adds
    # coverage, so no figure already stated can change under it. Prices (18)
    # point this entry at rows when they arrive, being corrections-capable...
    "rates": None,
    # ...and corporate actions (52), whose reversal is remove-and-rebuild.
    "corporate_actions": None,
}


@dataclass(frozen=True)
class InputDigest:
    row_count: int
    digest: str


@dataclass(frozen=True)
class DriftedInput:
    """One input class whose stored fingerprint no longer matches the current
    inputs. `stored_count` is None when the subject never stamped the class."""

    input_class: str
    stored_count: int | None
    current_count: int


def drifted(stored: dict[str, InputDigest], current: dict[str, InputDigest]) -> list[DriftedInput]:
    """What no longer matches, by input class — empty means the subject's
    stored rows are authoritative. The one comparison behind every staleness
    verdict, for materialisations and reports alike."""
    changed = [
        DriftedInput(
            input_class=input_class,
            stored_count=stored[input_class].row_count if input_class in stored else None,
            current_count=digest.row_count,
        )
        for input_class, digest in current.items()
        if stored.get(input_class) != digest
    ]
    # A class the registry no longer computes — a refactor, not data — still
    # means the stored rows rest on inputs nothing vouches for.
    changed += [
        DriftedInput(
            input_class=input_class, stored_count=stored[input_class].row_count, current_count=0
        )
        for input_class in stored
        if input_class not in current
    ]
    return changed


def current(connection: Connection) -> dict[str, InputDigest]:
    """The fingerprint of the inputs as they stand on this snapshot."""
    fingerprint = {}
    for input_class, source in INPUT_CLASSES.items():
        if source is None:
            fingerprint[input_class] = InputDigest(row_count=0, digest=NOTHING)
            continue
        counted = connection.execute(
            text(
                "SELECT count(*)::int AS row_count,"
                " encode(sha256(convert_to(coalesce("
                "string_agg(line, chr(10) ORDER BY line COLLATE \"C\"), ''), 'UTF8')), 'hex')"
                f" AS digest FROM ({source}) AS input_rows"
            )
        ).one()
        fingerprint[input_class] = InputDigest(row_count=counted.row_count, digest=counted.digest)
    return fingerprint


def stored(connection: Connection, subject: str) -> dict[str, InputDigest]:
    """The fingerprint the subject's last materialisation stamped — empty when
    none has ever run."""
    return {
        row.input_class: InputDigest(row_count=row.row_count, digest=row.digest)
        for row in connection.execute(
            text(
                "SELECT input_class, row_count, digest FROM input_fingerprint"
                " WHERE subject = :subject"
            ),
            {"subject": subject},
        )
    }


def record(connection: Connection, subject: str, fingerprint: dict[str, InputDigest]) -> None:
    connection.execute(
        text("DELETE FROM input_fingerprint WHERE subject = :subject"), {"subject": subject}
    )
    connection.execute(
        text(
            "INSERT INTO input_fingerprint (subject, input_class, row_count, digest)"
            " VALUES (:subject, :input_class, :row_count, :digest)"
        ),
        [
            {
                "subject": subject,
                "input_class": input_class,
                "row_count": digest.row_count,
                "digest": digest.digest,
            }
            for input_class, digest in fingerprint.items()
        ],
    )
