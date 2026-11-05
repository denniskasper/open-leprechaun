from fastapi import APIRouter
from pydantic import BaseModel

from open_leprechaun.services.meta import InstanceInfo, describe_instance
from open_leprechaun.settings import Environment, SettingsDep

router = APIRouter(tags=["meta"])


class MetaResponse(BaseModel):
    environment: Environment
    version: str
    # The machine a development instance runs on; never stated in production.
    host: str | None

    @classmethod
    def of(cls, info: InstanceInfo) -> MetaResponse:
        return cls(environment=info.environment, version=info.version, host=info.host)


@router.get(
    "/meta",
    summary="Identify the running instance: its environment, build and, in development, machine",
    response_model=MetaResponse,
)
def read_meta(settings: SettingsDep) -> MetaResponse:
    # Public on purpose: the UI shows the environment badge and version line
    # before anyone is logged in, and neither is a secret — nor is a dev box's
    # name, which production never states.
    return MetaResponse.of(describe_instance(settings))
