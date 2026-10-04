"""The eToro statement connector (ticket 50): a broker that offers no API,
served by the account statement it exports.

What the connector declares about this export, and holds it to:

- The file is the account statement as an XLSX workbook, exported with the
  account language set to English — the sheets and their headers are
  translated with the account, and only the English ones are read. Columns
  are found by their header, never by position: the layout gains and
  reorders columns between releases.
- Timestamps are "DD/MM/YYYY HH:MM:SS" on the UTC clock, as text or as the
  workbook's own date serial; both read as the same instant.
- Amounts are whole US dollars — the account is kept in dollars whatever the
  security is priced in — and units are whole units of the security,
  fractions included. A statement of an account kept in another currency is
  a variant this connector refuses.
- The **Account Activity** sheet is the statement's ledger: every row that
  moved the balance, and the only sheet a record is made from. The Closed
  Positions and Dividends sheets are read as lookups beside it, joined by
  Position ID — they alone state an ISIN, and the tax withheld from a
  dividend.

A position is a security only where the statement calls it a stock or an ETF
and it was neither leveraged nor short. A security is named by its ISIN
wherever the statement states one — on its closed position, on a dividend it
paid, or on another position in the same ticker. A position still open that
never paid states none: its ticker is then all there is, handed on as a
resolution hint for the ledger to answer.

What the statement states that this port cannot express is passed over by
name, never landed and never dropped: a contract for difference with every
row it moved, a coin (a statement names it by a ticker alone, and the broker
port names nothing that way), a split, and any row type this connector does
not know — the vocabulary is not published, so an unknown word is reported,
not guessed at and not a reason to refuse the file.

The statement reports no German tax withheld at source — it has no column
for one — so none is declared. A dividend's foreign withholding is stated
without the country that took it; the country recorded is the one the paying
security's ISIN names, which the parsed file says out loud.
"""

import base64
import binascii
import re
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from open_leprechaun.ports.broker import (
    BrokerHarvest,
    CoveredPeriod,
    NormalizedAccountFee,
    NormalizedDividend,
    NormalizedFee,
    NormalizedSecurity,
    NormalizedSecurityTrade,
    PassedOver,
)
from open_leprechaun.ports.csv_connector import FileRejectedError, ParsedFile
from open_leprechaun.ports.exchange import NormalizedCashMovement
from open_leprechaun.ports.workbook import Cell, Sheets, WorkbookError, read_workbook

_CURRENCY = "USD"

_ACTIVITY = "Account Activity"
_CLOSED = "Closed Positions"
_DIVIDENDS = "Dividends"
_SUMMARY = "Account Summary"
_ENGLISH_SHEETS = (_ACTIVITY, _CLOSED, _DIVIDENDS, _SUMMARY, "Financial Summary")

_ACTIVITY_COLUMNS = (
    "Date",
    "Type",
    "Details",
    "Amount",
    "Units / Contracts",
    "Position ID",
    "Asset type",
)
# Headers a release renamed, read as the column they became.
_RENAMED = {"Units": "Units / Contracts"}

# Asset types that are a security where the position is unleveraged and long.
_SECURITY_TYPES = frozenset({"stocks", "stock", "etf", "etfs"})

_OPENED = "Open Position"
_CLOSED_ROW = "Position closed"

_CASH_IN = frozenset({"Deposit", "Withdraw Request Cancelled"})
_CASH_OUT = frozenset({"Withdraw Request"})
_ACCOUNT_FEES = frozenset({"Withdraw Fee", "Deposit Conversion Fee", "Withdrawal Conversion Fee"})
_TRADE_FEES = frozenset({"Commission", "SDRT"})
# Rows that state a setting or a bookkeeping step and move no cash.
_MOVES_NOTHING = frozenset(
    {
        "Edit Stop Loss",
        "Start Copy",
        "Stop Copy",
        "Account balance to mirror",
        "Mirror balance to account",
    }
)

_ISIN = re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9]")
_PLAIN_NUMBER = re.compile(r"-?\d+(\.\d+)?")
_TICKER_SUFFIX = re.compile(r"\s*\([^()]*\)\s*$")
# An opening may state its leverage beside the paper: "NVDA/USD x2".
_LEVERAGE = re.compile(r"(?:\bx|leverage:\s*)(\d+)\b", re.IGNORECASE)
_SERIAL_EPOCH = datetime(1899, 12, 30)
# A workbook stores numbers as doubles; nothing a statement states is finer
# than this, and the binary noise sits far below it.
_NOISE_FLOOR = Decimal("0.00000001")


class EtoroStatementConnector:
    connector = "etoro"
    name = "eToro"
    expects = (
        "The account statement eToro exports as an XLSX workbook (Settings → Account →"
        " Account statement), with the account language set to English. Amounts are read"
        " as whole US dollars and units as whole units of the security."
    )
    timezone = "UTC"
    file_format = "xlsx"

    def parse(self, content: str) -> ParsedFile:
        sheets = self._sheets(content)
        return _Statement(sheets, ZoneInfo(self.timezone)).parsed()

    def _sheets(self, content: str) -> Sheets:
        try:
            sheets = read_workbook(base64.b64decode(content, validate=True))
        except (binascii.Error, ValueError, WorkbookError) as failed:
            raise FileRejectedError(
                "This is not an eToro account statement — the file is not a readable"
                " workbook. " + self.expects
            ) from failed
        if _ACTIVITY not in sheets:
            if not any(name in sheets for name in _ENGLISH_SHEETS):
                raise FileRejectedError(
                    "This workbook carries none of the statement's sheets under their"
                    " English names — export the statement with the account language set"
                    " to English."
                )
            raise FileRejectedError(
                "This is not an eToro account statement — it has no 'Account Activity'"
                " sheet. " + self.expects
            )
        return sheets


@dataclass(frozen=True)
class _Row:
    """One Account Activity row, read. `number` is its row in the sheet."""

    number: int
    at: datetime
    type: str
    details: str
    amount: Decimal
    units: Decimal | None
    position_id: str
    asset_type: str

    @property
    def cash(self) -> Decimal:
        """What the row moved the balance by: an opening states its stake as
        a positive amount that left; every other row is signed already."""
        return -self.amount if self.type == _OPENED else self.amount


@dataclass(frozen=True)
class _Closed:
    isin: str | None
    name: str
    type: str
    leveraged_or_short: bool


@dataclass(frozen=True)
class _Withheld:
    """One row of the Dividends sheet: the net it states and what was taken
    before it."""

    net: Decimal
    withheld: Decimal
    isin: str | None


@dataclass
class _Trade:
    """A trade being assembled: its fees arrive as rows of their own."""

    row: _Row
    side: str
    security: NormalizedSecurity
    fees: list[NormalizedFee] = field(default_factory=list)


class _Statement:
    """One workbook, read once: the lookup sheets first, then the activity
    row by row."""

    def __init__(self, sheets: Sheets, zone: ZoneInfo) -> None:
        self._zone = zone
        self._sheets = sheets
        self._closed: dict[str, _Closed] = {}
        self._isin_of: dict[str, str] = {}
        self._name_of: dict[str, str] = {}
        self._withheld: dict[tuple[str, date], list[_Withheld]] = defaultdict(list)
        self._read_closed_positions()
        self._read_dividends()
        self._rows = self._read_activity()
        self._asset_types: dict[str, str] = {}
        self._leveraged: set[str] = set()
        for row in self._rows:
            if row.position_id and row.asset_type:
                self._asset_types.setdefault(row.position_id, row.asset_type)
            stated = _LEVERAGE.search(row.details) if row.type == _OPENED else None
            if stated and int(stated.group(1)) > 1:
                self._leveraged.add(row.position_id)
        self._ticker_of = self._tickers()
        self._ticker_isin, self._ticker_name = self._by_ticker()

        self._ids: Counter[str] = Counter()
        self._moves_nothing: Counter[str] = Counter()
        self._passed_over: list[PassedOver] = []
        self._cash_left_out = False
        self._inferred_country = False

    # --- Reading the sheets ---

    def _table(self, sheet: str, required: tuple[str, ...]) -> list[tuple[int, dict[str, Cell]]]:
        """A sheet's rows keyed by header, each with its row number. A sheet
        the workbook lacks is no rows; one lacking a column it must carry
        refuses the file."""
        rows = self._sheets.get(sheet) or []
        if not rows:
            return []
        header = [_RENAMED.get(_text(cell), _text(cell)) for cell in rows[0]]
        missing = [column for column in required if column not in header]
        if missing:
            raise FileRejectedError(
                f"The '{sheet}' sheet does not carry the column"
                f" {', '.join(repr(column) for column in missing)} — an older or translated"
                " layout this connector cannot read. Export the statement again, with the"
                " account language set to English."
            )
        return [
            (number, dict(zip(header, cells, strict=False)))
            for number, cells in enumerate(rows[1:], start=2)
            if any(_text(cell) for cell in cells)
        ]

    def _read_closed_positions(self) -> None:
        for number, record in self._table(_CLOSED, ("Position ID",)):
            position_id = _text(record.get("Position ID"))
            leverage = _number(record.get("Leverage"), _CLOSED, number)
            self._closed[position_id] = _Closed(
                isin=_isin(record.get("ISIN")),
                name=_name(_text(record.get("Action"))),
                type=_text(record.get("Type")),
                leveraged_or_short=(leverage is not None and leverage != 1)
                or _text(record.get("Long / Short")).lower() == "short",
            )
            closed = self._closed[position_id]
            if closed.isin:
                self._isin_of[position_id] = closed.isin
            if closed.name:
                self._name_of[position_id] = closed.name

    def _read_dividends(self) -> None:
        required = ("Date of Payment", "Net Dividend Received (USD)", "Position ID")
        for number, record in self._table(_DIVIDENDS, required):
            position_id = _text(record.get("Position ID"))
            paid_on = _instant(record.get("Date of Payment"), self._zone, _DIVIDENDS, number)
            isin = _isin(record.get("ISIN"))
            if isin:
                self._isin_of.setdefault(position_id, isin)
            name = _name(_text(record.get("Instrument Name")))
            if name:
                self._name_of.setdefault(position_id, name)
            net = _number(record.get("Net Dividend Received (USD)"), _DIVIDENDS, number)
            withheld = _number(record.get("Withholding Tax Amount (USD)"), _DIVIDENDS, number)
            self._withheld[position_id, paid_on.astimezone(self._zone).date()].append(
                _Withheld(net=net or Decimal(0), withheld=withheld or Decimal(0), isin=isin)
            )

    def _read_activity(self) -> list[_Row]:
        rows = []
        for number, record in self._table(_ACTIVITY, _ACTIVITY_COLUMNS):
            amount = _number(record.get("Amount"), _ACTIVITY, number)
            rows.append(
                _Row(
                    number=number,
                    at=_instant(record.get("Date"), self._zone, _ACTIVITY, number),
                    type=_text(record.get("Type")),
                    details=_text(record.get("Details")),
                    amount=amount or Decimal(0),
                    units=_number(record.get("Units / Contracts"), _ACTIVITY, number),
                    position_id=_text(record.get("Position ID")),
                    asset_type=_text(record.get("Asset type")),
                )
            )
        return rows

    def _tickers(self) -> dict[str, str]:
        """Each position's ticker, from the rows that name the paper —
        "AAPL/USD" is the ticker and the currency it is quoted in."""
        tickers: dict[str, str] = {}
        for row in self._rows:
            if row.position_id and row.type in (_OPENED, _CLOSED_ROW, "Dividend"):
                ticker = row.details.split("/")[0].strip()
                if ticker:
                    tickers.setdefault(row.position_id, ticker)
        return tickers

    def _by_ticker(self) -> tuple[dict[str, str], dict[str, str]]:
        """What the statement says of a ticker through any position in it. A
        ticker two ISINs answer to names neither."""
        isins: dict[str, set[str]] = defaultdict(set)
        names: dict[str, str] = {}
        for position_id, ticker in self._ticker_of.items():
            if position_id in self._isin_of and self._is_security(position_id):
                isins[ticker].add(self._isin_of[position_id])
                if position_id in self._name_of:
                    names.setdefault(ticker, self._name_of[position_id])
        return {t: next(iter(found)) for t, found in isins.items() if len(found) == 1}, names

    # --- What a position is ---

    def _asset_type(self, position_id: str) -> str:
        if position_id in self._asset_types:
            return self._asset_types[position_id]
        closed = self._closed.get(position_id)
        return closed.type if closed else ""

    def _is_security(self, position_id: str) -> bool:
        closed = self._closed.get(position_id)
        if position_id in self._leveraged or (closed is not None and closed.leveraged_or_short):
            return False
        return self._asset_type(position_id).lower() in _SECURITY_TYPES

    def _why_not(self, position_id: str) -> str:
        asset_type = self._asset_type(position_id)
        if asset_type.lower() in _SECURITY_TYPES or asset_type.lower() == "cfd":
            return "a leveraged or short position is a contract for difference, not a security"
        if asset_type.lower() == "crypto":
            return "a coin, which the statement names by a ticker alone"
        if asset_type:
            return f"of asset type {asset_type!r}, which this connector cannot read"
        return "whose asset type the statement does not state"

    def _security(self, position_id: str) -> NormalizedSecurity | None:
        ticker = self._ticker_of.get(position_id, "")
        isin = self._isin_of.get(position_id) or self._ticker_isin.get(ticker)
        if not ticker and not isin:
            return None
        name = self._name_of.get(position_id) or self._ticker_name.get(ticker) or ticker
        return NormalizedSecurity(isin=isin, symbol=ticker or isin, name=name or isin)

    # --- Making the records ---

    def parsed(self) -> ParsedFile:
        trades: dict[str, list[_Trade]] = defaultdict(list)
        fees: list[_Row] = []
        dividends: list[NormalizedDividend] = []
        cash_movements: list[NormalizedCashMovement] = []
        account_fees: list[NormalizedAccountFee] = []
        left_out: dict[str, list[_Row]] = defaultdict(list)

        for row in self._rows:
            if row.position_id and not self._is_security(row.position_id):
                left_out[row.position_id].append(row)
            elif row.type in _MOVES_NOTHING:
                self._moves_nothing[row.type] += 1
            elif row.position_id:
                self._position_row(row, trades, fees, dividends)
            elif (row.type in _CASH_IN and row.amount > 0) or (
                row.type in _CASH_OUT and row.amount < 0
            ):
                cash_movements.append(
                    NormalizedCashMovement(
                        external_id=self._id(row),
                        occurred_at=row.at,
                        direction="in" if row.type in _CASH_IN else "out",
                        currency=_CURRENCY,
                        amount=abs(row.amount),
                    )
                )
            elif row.type in _ACCOUNT_FEES and row.amount < 0:
                account_fees.append(
                    NormalizedAccountFee(
                        external_id=self._id(row),
                        occurred_at=row.at,
                        amount=abs(row.amount),
                        currency=_CURRENCY,
                    )
                )
            elif row.type == "Interest Payment" and row.amount > 0:
                dividends.append(
                    NormalizedDividend(
                        external_id=self._id(row),
                        occurred_at=row.at,
                        kind="interest",
                        amount=row.amount,
                        currency=_CURRENCY,
                    )
                )
            else:
                self._pass_over(row)

        # A fee names its trade by position alone, and may be listed on
        # either side of it — so fees attach once every trade is known.
        for row in fees:
            self._fee(row, trades[row.position_id])
        for position_id, rows in left_out.items():
            self._pass_over_position(position_id, rows)

        landed = [trade for of_position in trades.values() for trade in of_position]
        return ParsedFile(
            statement=BrokerHarvest(
                covered=self._covered(),
                trades=tuple(_normalized(trade, self._id) for trade in landed),
                dividends=tuple(dividends),
                cash_movements=tuple(cash_movements),
                account_fees=tuple(account_fees),
                passed_over=tuple(self._passed_over),
            ),
            warnings=self._warnings(trades),
        )

    def _position_row(
        self,
        row: _Row,
        trades: dict[str, list[_Trade]],
        fees: list[_Row],
        dividends: list[NormalizedDividend],
    ) -> None:
        """One row of a position that is a security."""
        security = self._security(row.position_id)
        if row.type in (_OPENED, _CLOSED_ROW):
            if security is None or not row.units or row.units <= 0 or row.amount <= 0:
                # A close that returned nothing, or a row missing what makes
                # it a trade: named for the Admin, since no leg can state it.
                self._cash_left_out = self._cash_left_out or row.amount != 0
                self._passed_over.append(
                    PassedOver(
                        external_id=self._id(row),
                        occurred_at=row.at,
                        description=(
                            f"{row.type} on position {row.position_id} in"
                            f" {row.details or 'an unnamed paper'} was left out — it states"
                            " no ticker, no units or no positive amount, so it is no trade"
                            " the ledger can record; record it by hand."
                        ),
                    )
                )
                return
            side = "buy" if row.type == _OPENED else "sell"
            trades[row.position_id].append(_Trade(row=row, side=side, security=security))
        elif row.type in _TRADE_FEES and row.amount <= 0:
            fees.append(row)
        elif row.type == "Dividend" and row.amount > 0 and security is not None:
            dividends.append(self._dividend(row, security))
        elif row.type == "corp action: Split":
            self._passed_over.append(
                PassedOver(
                    external_id=self._id(row),
                    occurred_at=row.at,
                    description=(
                        f"{row.type} {row.details} — record it as a Corporate Action; the"
                        " units of earlier rows are as they were before it."
                    ),
                )
            )
        else:
            self._pass_over(row)

    def _fee(self, row: _Row, of_position: list[_Trade]) -> None:
        """A commission or a stamp duty is its own row, a cost of the trade
        it names: the opening, or the close it follows."""
        if row.amount == 0:
            self._moves_nothing[row.type] += 1
            return
        sales = [trade for trade in of_position if trade.side == "sell"]
        # The close the fee follows; failing that, the one it precedes.
        closes = [trade for trade in sales if trade.row.at <= row.at][-1:] or sales[:1]
        opening = [trade for trade in of_position if trade.side == "buy"]
        on_close = row.details.lower() == "on close"
        target = (closes if on_close else opening) or (opening if on_close else closes)
        if not target:
            self._pass_over(row, why="the trade it was charged on is not in this statement")
            return
        target[0].fees.append(
            NormalizedFee(
                name=row.type,
                amount=abs(row.amount),
                currency=_CURRENCY,
                charged_against="security",
            )
        )

    def _dividend(self, row: _Row, security: NormalizedSecurity) -> NormalizedDividend:
        """The activity states the instant and the net; the Dividends sheet,
        where it lists this payment, what was withheld before it."""
        paid_on = row.at.astimezone(self._zone).date()
        # The sheet dates a payment by its day alone, and the activity may
        # book it a day to either side; the net must be the same to the cent.
        listed, stated = next(
            (
                (entries, entry)
                for offset in (0, -1, 1)
                for entries in [
                    self._withheld.get((row.position_id, paid_on + timedelta(days=offset)), [])
                ]
                for entry in entries
                if entry.net == row.amount
            ),
            ([], None),
        )
        withholding: dict = {}
        if stated is not None:
            listed.remove(stated)
            if stated.withheld > 0:
                withholding["gross_amount"] = _tidy(row.amount + stated.withheld)
                withholding["gross_currency"] = _CURRENCY
                isin = stated.isin or security.isin
                if isin:
                    # The statement names no country beside the tax; the
                    # paying security's ISIN is what it offers.
                    self._inferred_country = True
                    withholding["foreign_withholding"] = stated.withheld
                    withholding["source_country"] = isin[:2]
        return NormalizedDividend(
            external_id=self._unique(f"{row.position_id}:dividend:{paid_on.isoformat()}"),
            occurred_at=row.at,
            kind="dividend",
            amount=row.amount,
            currency=_CURRENCY,
            security=security,
            **withholding,
        )

    def _pass_over(self, row: _Row, why: str = "the statement does not say what it is") -> None:
        if row.amount == 0:
            self._moves_nothing[row.type or "(no type)"] += 1
            return
        self._cash_left_out = True
        where = f" on position {row.position_id}" if row.position_id else ""
        self._passed_over.append(
            PassedOver(
                external_id=self._id(row),
                occurred_at=row.at,
                description=(
                    f"{row.type} of {row.amount:f} {_CURRENCY}{where} was left out — {why}."
                ),
            )
        )

    def _pass_over_position(self, position_id: str, rows: list[_Row]) -> None:
        """A position that is no security, named once with everything it
        moved."""
        moved = [row for row in rows if row.amount != 0]
        for row in rows:
            if row.amount == 0:
                self._moves_nothing[row.type or "(no type)"] += 1
        if not moved:
            return
        self._cash_left_out = True
        paper = next((row.details for row in rows if row.type == _OPENED), None)
        paper = paper or self._ticker_of.get(position_id) or "an unnamed paper"
        count = "1 row" if len(moved) == 1 else f"{len(moved)} rows"
        net = _tidy(sum((row.cash for row in moved), Decimal(0)))
        self._passed_over.append(
            PassedOver(
                external_id=f"{position_id}:left-out",
                occurred_at=moved[0].at,
                description=(
                    f"Position {position_id} in {paper} — {self._why_not(position_id)} — was"
                    f" left out with the {count} that moved its cash (net {net:f} {_CURRENCY})."
                ),
            )
        )

    # --- Identifiers, the period, and what is said beside the records ---

    def _id(self, row: _Row) -> str:
        """An identifier that is the same in every statement covering the
        row. A trade is named by its position; anything else by what the row
        itself states, since the statement gives it no identifier."""
        at = row.at.astimezone(UTC).replace(tzinfo=None).isoformat()
        if row.type == _OPENED:
            return self._unique(f"{row.position_id}:open")
        if row.type == _CLOSED_ROW:
            return self._unique(f"{row.position_id}:close:{at}")
        slug = re.sub(r"[^a-z0-9]+", "-", row.type.lower()).strip("-")
        owner = f"{row.position_id}:" if row.position_id else ""
        return self._unique(f"{owner}{slug}:{at}:{row.amount:f}")

    def _unique(self, identifier: str) -> str:
        """Rows that state the same thing twice are two facts: the second
        and later ones are numbered, in the order the statement lists them."""
        self._ids[identifier] += 1
        seen = self._ids[identifier]
        return identifier if seen == 1 else f"{identifier}:{seen}"

    def _covered(self) -> CoveredPeriod:
        """The period the Account Summary states, or failing that the span
        of the activity itself."""
        stated: dict[str, datetime] = {}
        currency = ""
        for number, cells in enumerate(self._sheets.get(_SUMMARY) or [], start=1):
            labelled = [cell for cell in cells if _text(cell)]
            if len(labelled) < 2:
                continue
            label, value = _text(labelled[0]), labelled[1]
            if label in ("Start Date", "End Date"):
                stated[label] = _instant(value, self._zone, _SUMMARY, number)
            elif label == "Currency":
                currency = _text(value)
        if currency and currency != _CURRENCY:
            raise FileRejectedError(
                f"This statement states its amounts in {currency}, and this connector reads"
                f" an account kept in {_CURRENCY} — a variant it cannot support."
            )
        if "Start Date" in stated and "End Date" in stated:
            return CoveredPeriod(start=stated["Start Date"], end=stated["End Date"])
        if not self._rows:
            raise FileRejectedError(
                "This statement states neither the period it covers nor any activity."
            )
        instants = [row.at for row in self._rows]
        return CoveredPeriod(start=min(instants), end=max(instants))

    def _warnings(self, trades: dict[str, list[_Trade]]) -> tuple[str, ...]:
        warnings = []
        if self._moves_nothing:
            total = sum(self._moves_nothing.values())
            named = ", ".join(
                kind if count == 1 else f"{kind} ({count})"
                for kind, count in sorted(self._moves_nothing.items())
            )
            warnings.append(
                f"1 row that moves nothing was left out: {named}."
                if total == 1
                else f"{total} rows that move nothing were left out: {named}."
            )
        orphaned = sum(
            1
            for of_position in trades.values()
            if not any(trade.side == "buy" for trade in of_position)
            for trade in of_position
        )
        if orphaned:
            subject = "1 sale closes" if orphaned == 1 else f"{orphaned} sales close"
            warnings.append(
                f"{subject} a position this statement shows no purchase of — import the"
                " statement covering the purchase too, or the ledger sells what it never"
                " bought."
            )
        # A contract for difference's dividend adjustments are listed there
        # too, and were passed over with their position.
        unlisted = sum(
            len(entries)
            for (position_id, _), entries in self._withheld.items()
            if self._is_security(position_id) or not self._asset_type(position_id)
        )
        if unlisted:
            noun = "row" if unlisted == 1 else "rows"
            warnings.append(
                f"{unlisted} {noun} of the '{_DIVIDENDS}' sheet matched no dividend of a"
                f" security in the '{_ACTIVITY}' sheet and stated nothing."
            )
        if self._inferred_country:
            warnings.append(
                "The statement names no country beside a tax withheld from a dividend; each"
                " is recorded under the country of the paying security's ISIN — correct it"
                " where a depositary receipt was taxed elsewhere."
            )
        if self._cash_left_out:
            warnings.append(
                "What was left out moved cash, so the Depot's cash will differ from the"
                " statement's until it is recorded."
            )
        return tuple(warnings)


def _normalized(trade: _Trade, identify: Callable[[_Row], str]) -> NormalizedSecurityTrade:
    return NormalizedSecurityTrade(
        external_id=identify(trade.row),
        occurred_at=trade.row.at,
        security=trade.security,
        side=trade.side,
        quantity=trade.row.units,
        settled_amount=trade.row.amount,
        settlement_currency=_CURRENCY,
        fees=tuple(trade.fees),
    )


def _tidy(value: Decimal) -> Decimal:
    """A stored number without its binary noise, written plainly."""
    return Decimal(f"{value.quantize(_NOISE_FLOOR).normalize():f}")


def _text(cell: Cell) -> str:
    """A cell as text, trimmed. The statement writes "-" where it has
    nothing to say, which reads as nothing."""
    if cell is None:
        return ""
    text = f"{_tidy(cell):f}" if isinstance(cell, Decimal) else cell.strip()
    return "" if text == "-" else text


def _number(cell: Cell, sheet: str, row: int) -> Decimal | None:
    """A cell as a number, whether the workbook stored one or its text."""
    if isinstance(cell, Decimal):
        return _tidy(cell)
    text = _text(cell).removesuffix("%").strip()
    if not text:
        return None
    if not _PLAIN_NUMBER.fullmatch(text):
        raise FileRejectedError(
            f"Row {row} of the '{sheet}' sheet states {text!r} where a plain number belongs"
            " — a number format this connector cannot read."
        )
    return _tidy(Decimal(text))


def _instant(cell: Cell, zone: ZoneInfo, sheet: str, row: int) -> datetime:
    """A cell as an instant: the workbook's date serial, or the statement's
    own "DD/MM/YYYY HH:MM:SS" — read on the declared clock, answered in UTC."""
    if isinstance(cell, Decimal):
        naive = _SERIAL_EPOCH + timedelta(seconds=int((cell * 86400).to_integral_value()))
    else:
        naive = None
        for shape in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
            try:
                naive = datetime.strptime(_text(cell), shape)
                break
            except ValueError:
                continue
        if naive is None:
            raise FileRejectedError(
                f"Row {row} of the '{sheet}' sheet carries a timestamp this connector cannot"
                f" read ({_text(cell)!r}) — it reads DD/MM/YYYY HH:MM:SS."
            )
    return naive.replace(tzinfo=zone).astimezone(UTC)


def _isin(cell: Cell) -> str | None:
    text = _text(cell).upper()
    return text if _ISIN.fullmatch(text) else None


def _name(text: str) -> str:
    """A paper's name out of "Buy Apple (AAPL)" or "Apple (AAPL)": the
    direction older layouts lead with and the ticker in brackets are not part
    of it."""
    for prefix in ("Buy ", "Sell "):
        text = text.removeprefix(prefix)
    return _TICKER_SUFFIX.sub("", text).strip()
