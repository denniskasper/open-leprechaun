"""The application's security search provider (ticket 44), as a dependency.

onvista — its one query endpoint accepts ISIN, WKN, ticker and name alike
without a key. One provider per process, built on first use and exposed the
way the engine is (db.get_engine), so tests can bind the app to fakes of the
port without touching global state.
"""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from open_leprechaun.ports.onvista import OnvistaProvider
from open_leprechaun.ports.security_search import SecuritySearchProvider


@lru_cache
def get_security_search() -> SecuritySearchProvider:
    return OnvistaProvider()


SecuritySearchDep = Annotated[SecuritySearchProvider, Depends(get_security_search)]
