"""The application's reference-rate source (ADR-0017), as a dependency.

One ECB source per process, built on first use — exposed the way the engine
is (db.get_engine), so tests can bind the app to the port's fake without
touching global state.
"""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from open_leprechaun.ports.ecb import EcbReferenceRateSource
from open_leprechaun.ports.reference_rates import ReferenceRateSource


@lru_cache
def get_reference_rate_source() -> ReferenceRateSource:
    return EcbReferenceRateSource()


ReferenceRateSourceDep = Annotated[ReferenceRateSource, Depends(get_reference_rate_source)]
