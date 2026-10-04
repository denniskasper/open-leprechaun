"""Writes and reads over what asking each data provider last came to
(ticket 55).

`provider_status` keeps the latest answer and the latest failure side by side
— the health panel needs both — and `condition` says which of them is the
present. `provider_affected_instrument` is the latest price refresh's own
finding: the Instruments it left without a fresh price while the provider was
failing.
"""

from collections.abc import Collection
from datetime import datetime
from typing import Literal

from sqlalchemy import Engine, Row, text

Condition = Literal["rate_limited", "outage"]


def record_success(engine: Engine, provider: str, *, at: datetime) -> None:
    """The provider answered: its condition is over, and with it whatever
    that condition affected. The last error stays — it is still the last
    error."""
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM provider_affected_instrument WHERE provider = :provider"),
            {"provider": provider},
        )
        connection.execute(
            text(
                "INSERT INTO provider_status (provider, last_success_at) VALUES (:provider, :at)"
                " ON CONFLICT (provider) DO UPDATE"
                " SET last_success_at = excluded.last_success_at, condition = NULL"
            ),
            {"provider": provider, "at": at},
        )


def record_failure(
    engine: Engine, provider: str, *, condition: Condition, error: str, at: datetime
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO provider_status (provider, last_error_at, last_error, condition)"
                " VALUES (:provider, :at, :error, :condition)"
                " ON CONFLICT (provider) DO UPDATE"
                " SET last_error_at = excluded.last_error_at, last_error = excluded.last_error,"
                " condition = excluded.condition"
            ),
            {"provider": provider, "at": at, "error": error, "condition": condition},
        )


def replace_affected(engine: Engine, provider: str, instrument_ids: Collection[int]) -> None:
    """State afresh which Instruments the provider's failure affects — none,
    for an empty collection. A provider nothing has recorded a call of can
    affect nothing, so there is nothing to write for it."""
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM provider_affected_instrument WHERE provider = :provider"),
            {"provider": provider},
        )
        if instrument_ids:
            connection.execute(
                text(
                    "INSERT INTO provider_affected_instrument (provider, instrument_id)"
                    " SELECT :provider, i.id FROM instrument i"
                    " WHERE i.id = ANY(CAST(:ids AS integer[]))"
                    " AND EXISTS (SELECT 1 FROM provider_status s WHERE s.provider = :provider)"
                    # Two refreshes may state the same finding at once.
                    " ON CONFLICT DO NOTHING"
                ),
                {"provider": provider, "ids": list(instrument_ids)},
            )


def statuses(engine: Engine) -> dict[str, Row]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT provider, last_success_at, last_error_at, last_error, condition"
                " FROM provider_status"
            )
        ).all()
    return {row.provider: row for row in rows}


def affected_instruments(engine: Engine) -> list[Row]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT a.provider, i.id, i.symbol, i.name"
                    " FROM provider_affected_instrument a"
                    " JOIN instrument i ON i.id = a.instrument_id"
                    " ORDER BY a.provider, i.symbol, i.id"
                )
            ).all()
        )
