"""The reference-rate port: the euro foreign exchange reference rate is the
canonical source for every EUR conversion (ticket 17, ADR-0017), and this is
the seam it is fetched through.

A source answers the published daily rates for one currency over a date range
— as published, units of currency per one euro, against the date each rate
represents. Days without a publication (weekends, TARGET closing days) are
simply absent; resolving them is the conversion service's rule, not the
source's.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class ReferenceRate:
    currency: str
    # The date the rate represents — the publication's reference date, not
    # the day it was fetched.
    rate_date: date
    # Units of currency per one euro, exactly as published.
    rate: Decimal


class ReferenceRateSource(Protocol):
    def daily_rates(self, currency: str, start: date, end: date) -> Sequence[ReferenceRate]: ...
