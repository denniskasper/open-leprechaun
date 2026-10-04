"""Reading an .xlsx workbook with the standard library alone: a zip archive
of XML parts, opened only as far as a connector needs — each sheet by its
name, as rows of cells.

A cell answers what the file stores, never an interpretation of it: text as
a string, a number as the Decimal its own digits spell — never through a
float — and nothing as None. Whether a number is an amount or a date serial
is the connector's knowledge, since it alone knows the column. Styles,
formulas and formatting are not read.

The file is somebody's upload, so it is held to bounds before it is trusted:
a part that inflates past the limit, or one that declares a document type —
where entity expansion lives — refuses the workbook.
"""

import io
import posixpath
import re
import zipfile
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree

Cell = str | Decimal | None
Sheets = dict[str, list[list[Cell]]]

# What one part may inflate to. A statement of years of activity is a few
# megabytes of XML; this is an order of magnitude beyond it.
_MAX_PART_BYTES = 64 * 1024 * 1024

_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_RELATIONSHIP = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PACKAGE = "{http://schemas.openxmlformats.org/package/2006/relationships}"

_COLUMN_LETTERS = re.compile(r"[A-Z]+")


class WorkbookError(Exception):
    """The bytes are not a workbook this reader can open — one sentence."""


def read_workbook(data: bytes) -> Sheets:
    """Every sheet of the workbook by its name, each a list of rows, each row
    a list of cells positioned by column — a cell the file leaves out is
    None. Raises WorkbookError and nothing else."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return _sheets(archive)
    except (
        zipfile.BadZipFile,
        ElementTree.ParseError,
        InvalidOperation,
        LookupError,
        ValueError,
    ) as failed:
        raise WorkbookError("The file is not a readable .xlsx workbook.") from failed


def _sheets(archive: zipfile.ZipFile) -> Sheets:
    targets = {
        relationship.get("Id"): relationship.get("Target", "")
        for relationship in _part(archive, "xl/_rels/workbook.xml.rels").iter(
            f"{_PACKAGE}Relationship"
        )
    }
    names = set(archive.namelist())
    strings = _shared_strings(archive) if "xl/sharedStrings.xml" in names else []
    sheets: Sheets = {}
    workbook = _part(archive, "xl/workbook.xml")
    properties = workbook.find(f"{_MAIN}workbookPr")
    if properties is not None and properties.get("date1904") in ("1", "true"):
        # Its date serials count from another day; reading them on the usual
        # one would put every date four years off.
        raise WorkbookError("The workbook counts its dates from 1904, which this reader does not.")
    for sheet in workbook.iter(f"{_MAIN}sheet"):
        target = targets[sheet.get(f"{_RELATIONSHIP}id")]
        # A target is relative to the workbook part unless it is rooted.
        path = target.lstrip("/") if target.startswith("/") else posixpath.join("xl", target)
        sheets[sheet.get("name", "")] = _rows(_part(archive, posixpath.normpath(path)), strings)
    return sheets


def _part(archive: zipfile.ZipFile, name: str) -> ElementTree.Element:
    if archive.getinfo(name).file_size > _MAX_PART_BYTES:
        raise WorkbookError("The workbook is larger than any statement this reader accepts.")
    with archive.open(name) as part:
        content = part.read(_MAX_PART_BYTES + 1)
    if len(content) > _MAX_PART_BYTES:
        raise WorkbookError("The workbook is larger than any statement this reader accepts.")
    if b"<!DOCTYPE" in content or b"<!ENTITY" in content:
        raise WorkbookError("The workbook declares a document type, which no export does.")
    return ElementTree.fromstring(content)


def _text(element: ElementTree.Element) -> str:
    """A string item's text: one run or several, phonetic hints left out."""
    return "".join(
        run.text or "" for run in element.iter(f"{_MAIN}t") if run not in _phonetic_runs(element)
    )


def _phonetic_runs(element: ElementTree.Element) -> set[ElementTree.Element]:
    return {run for phonetic in element.iter(f"{_MAIN}rPh") for run in phonetic.iter(f"{_MAIN}t")}


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    return [_text(item) for item in _part(archive, "xl/sharedStrings.xml").iter(f"{_MAIN}si")]


def _rows(sheet: ElementTree.Element, strings: list[str]) -> list[list[Cell]]:
    rows: list[list[Cell]] = []
    for row in sheet.iter(f"{_MAIN}row"):
        cells: list[Cell] = []
        for position, cell in enumerate(row.iter(f"{_MAIN}c")):
            reference = _COLUMN_LETTERS.match(cell.get("r", ""))
            # A cell names its column ("C5"); one that does not follows the
            # cell before it.
            column = _column_index(reference.group()) if reference else max(position, len(cells))
            cells.extend([None] * (column - len(cells)))
            cells.append(_value(cell, strings))
        rows.append(cells)
    return rows


def _column_index(letters: str) -> int:
    index = 0
    for letter in letters:
        index = index * 26 + (ord(letter) - ord("A") + 1)
    return index - 1


def _value(cell: ElementTree.Element, strings: list[str]) -> Cell:
    kind = cell.get("t", "n")
    if kind == "inlineStr":
        inline = cell.find(f"{_MAIN}is")
        return _text(inline) if inline is not None else None
    stored = cell.findtext(f"{_MAIN}v")
    if stored is None or stored == "":
        return None
    if kind == "s":
        return strings[int(stored)]
    if kind == "n":
        return Decimal(stored)
    # A formula's string, a boolean or an error: the text as stored.
    return stored
