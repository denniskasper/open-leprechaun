import socket
import subprocess
from dataclasses import dataclass
from functools import lru_cache

from open_leprechaun.settings import REPO_ROOT, Environment, Settings


@dataclass(frozen=True)
class InstanceInfo:
    """Which of the two instances this is, which build it is running and —
    in development only — which machine it runs on."""

    environment: Environment
    version: str
    host: str | None


def describe_instance(settings: Settings) -> InstanceInfo:
    """Development identifies by its checked-out commit — a box runs
    whatever is in the working copy, and the package version never changes
    between commits — and by the machine's name, since several boxes run a dev
    server side by side. Everything else runs a release, says which one, and
    keeps its machine to itself: the endpoint is public."""
    if settings.environment is Environment.development:
        version = _working_copy_commit() or settings.release_version
        host = socket.gethostname() or None
    else:
        version = settings.release_version
        host = None
    return InstanceInfo(environment=settings.environment, version=version, host=host)


@lru_cache
def _working_copy_commit() -> str | None:
    """The short hash of the checked-out commit, or None outside a git checkout."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None
