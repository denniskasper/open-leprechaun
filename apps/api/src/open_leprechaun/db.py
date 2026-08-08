from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from open_leprechaun.settings import get_settings


@lru_cache
def get_engine() -> Engine:
    """One pooled engine per process, built on first use.

    Exposed as a FastAPI dependency so that tests can bind the app to a
    different database without touching global state.
    """
    return create_engine(get_settings().database_url, pool_pre_ping=True)


EngineDep = Annotated[Engine, Depends(get_engine)]


def database_answers(engine: Engine) -> bool:
    """Whether the database is reachable at all.

    Connectivity rather than a domain query, so it lives with the engine. The
    repositories layer arrives with the first query that has a subject.
    """
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False
    return True
