"""The CSV connector registry: every exported file the ledger can read.

This is the one place connector names live on the way in (ADR-0008, ticket
32's "a registry so adding one touches no service, router or screen") — core
code reads entries generically and never branches on a name. Adding a
connector is adding an entry here; the picker on the Imports screen, the
preview and the commit follow from the entry alone.
"""

from open_leprechaun.ports.bitbox import BitBoxConnector
from open_leprechaun.ports.csv_connector import CsvConnector
from open_leprechaun.ports.ledger_live import LedgerLiveConnector

# Keyed by the connector string that stems every provenance source.
CONNECTORS: dict[str, CsvConnector] = {
    entry.connector: entry for entry in (LedgerLiveConnector(), BitBoxConnector())
}
