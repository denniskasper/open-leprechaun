# A broker's statement comes through the connector port, stating the broker port's records

## Status

accepted

## Context

Some brokers offer no API. Their history reaches the ledger only as the statement the Admin
exports — a file, so by shape of source it belongs to the **CSV Connector** port (ADR-0008). But
that port's record is a symbol and a quantity, which is all a wallet's export can say. A statement
says what a broker says: a security by its ISIN, a trade against the Depot's cash with its fees,
income with what was withheld. Those are the **Broker Adapter**'s Normalized records.

A statement is also not text. The one this was built for is a workbook.

And a statement can know less than an API: it may name a position by a ticker alone, stating the
ISIN only on some sheets — for a position that has closed or paid a dividend.

## Decision

A statement connector is a connector: one port, one registry, one preview-and-commit path, one
provenance scheme (`<connector>:<account>`). What it answers is the broker port's own records —
a parsed file carries either symbol rows or a statement, and **what the file yielded, never the
connector's name, decides how it lands**. A statement lands by the same translation a Broker
Adapter's harvest goes through, so both modes produce the same Transactions and neither is
second-class.

A connector declares its **file format**. A workbook travels as its bytes in base64 in the same
JSON field a CSV travels in as text, and is read with the standard library.

A security named **by ticker alone** is a resolution hint (ADR-0010): exactly one security in the
ledger may answer to it, by its symbol or a ticker alias, and the record lands under that
security's ISIN. Nothing is minted from a ticker. One that nothing or several things answer to
leaves its rows out with a sentence, and the rest of the statement lands.

## Considered Options

- **A fifth port for statements.** Rejected: it would differ from the connector port in nothing
  but its record type, and duplicate the registry, the routes and the screen.
- **Widen the symbol row until it can state a trade.** Rejected: a second, weaker description of
  a security trade beside the broker port's, with its own translation to keep in step.
- **Refuse a file that names any security by ticker alone.** Rejected: a position still open
  would bar every statement that shows it.
- **Mint a security from a ticker.** Rejected: that is keying on a symbol (ADR-0010).
- **A multipart upload for binary files.** Rejected: statements are small, and one JSON seam is
  less to hold than two.

## Consequences

- The broker port's security may state no ISIN. An adapter always states one; only a file may not.
- A row left out for want of an ISIN lands on a later import of the same file, once the ledger
  holds the security — deduplication makes the re-import safe.
- A broker served by import is current only as far as its last statement; the preview states the
  period each one covers.
