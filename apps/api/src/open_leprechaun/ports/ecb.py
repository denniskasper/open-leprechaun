"""The ECB implementation of the reference-rate port.

The euro foreign exchange reference rates, from the ECB's SDMX data API —
series `EXR/D.<currency>.EUR.SP00.A`, daily, units of currency per one euro.
Rates come back exactly as published: the observation's own reference date,
the value as a Decimal from its text, never through a float.

The API answers 404 for a period with no observations; that is an absence of
publications — a normal answer the conversion service turns into its gap rule
— not an outage. Any other failure raises, so an outage is never mistaken for
a gap.
"""

import csv
from datetime import date
from decimal import Decimal
from io import StringIO

import httpx

from open_leprechaun.ports.reference_rates import ReferenceRate

DATA_API = "https://data-api.ecb.europa.eu/service/data"


class EcbReferenceRateSource:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=10.0)

    def daily_rates(self, currency: str, start: date, end: date) -> list[ReferenceRate]:
        response = self._client.get(
            f"{DATA_API}/EXR/D.{currency}.EUR.SP00.A",
            params={
                "startPeriod": start.isoformat(),
                "endPeriod": end.isoformat(),
                "format": "csvdata",
            },
        )
        if response.status_code == httpx.codes.NOT_FOUND:
            return []
        response.raise_for_status()
        return [
            ReferenceRate(
                currency=currency,
                rate_date=date.fromisoformat(row["TIME_PERIOD"]),
                rate=Decimal(row["OBS_VALUE"]),
            )
            for row in csv.DictReader(StringIO(response.text))
        ]
