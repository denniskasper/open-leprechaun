from dataclasses import dataclass

from sqlalchemy import Engine

from open_leprechaun.db import database_answers


@dataclass(frozen=True)
class HealthStatus:
    """What the service can say about its own readiness."""

    database_up: bool

    @property
    def healthy(self) -> bool:
        """Healthy means every signal is good. There is one signal so far."""
        return self.database_up


def check_health(engine: Engine) -> HealthStatus:
    return HealthStatus(database_up=database_answers(engine))
