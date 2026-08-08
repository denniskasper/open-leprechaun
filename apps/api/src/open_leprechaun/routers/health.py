from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from open_leprechaun.db import EngineDep
from open_leprechaun.services.health import HealthStatus, check_health

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["up", "down"]

    @classmethod
    def of(cls, health: HealthStatus) -> HealthResponse:
        return cls(
            status="ok" if health.healthy else "degraded",
            database="up" if health.database_up else "down",
        )


@router.get(
    "/health",
    summary="Report whether the service and its database are answering",
    response_model=HealthResponse,
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": HealthResponse,
            "description": "The service is running but its database cannot be reached",
        }
    },
)
def read_health(response: Response, engine: EngineDep) -> HealthResponse:
    health = check_health(engine)
    if not health.healthy:
        # The body still describes what is wrong, so a caller reads it either way.
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse.of(health)
