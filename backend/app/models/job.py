"""Job request models. Credentials appear ONLY in RunRequest (POST /jobs/{id}/run), never in JobCreate."""

from typing import Annotated

from pydantic import Field, SecretStr, StringConstraints, field_validator

from .common import ObjectIdStr, StrictModel
from .plan import ConfigPlan, DevicePassword, _no_space_secret

RUNNING = ("queued", "connecting", "backing_up", "checking", "applying", "verifying", "saving", "rolling_back")
TERMINAL = ("success", "failed", "rolled_back", "blocked", "cancelled", "expired")
STATUSES = ("awaiting_approval", "ready", *RUNNING, *TERMINAL)
CANCELLABLE = ("awaiting_approval", "ready", "queued", "connecting", "backing_up", "checking")

LoginUser = Annotated[str, StringConstraints(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.@\\-]+$")]
LoginSecret = Annotated[SecretStr, Field(min_length=1, max_length=128)]


def _no_control(value: SecretStr | None) -> SecretStr | None:
    if value is not None and any(ord(c) < 32 or ord(c) == 127 for c in value.get_secret_value()):
        raise ValueError("must not contain control characters")
    return value


class JobCreate(StrictModel):
    device_id: ObjectIdStr
    plan: ConfigPlan
    note: Annotated[str, StringConstraints(max_length=200, pattern=r"^[A-Za-z0-9 _.,:/()@+=!'-]*$")] = ""


class RunRequest(StrictModel):
    """Device login (and the plan's own secrets) for one run. Held in memory only, never stored."""

    username: LoginUser
    password: LoginSecret
    enable_secret: LoginSecret | None = None
    ssh_user_password: DevicePassword | None = None  # password of the local user the plan creates
    new_enable_secret: DevicePassword | None = None  # enable secret the plan sets

    _check_login = field_validator("password", "enable_secret")(_no_control)
    _check_plan = field_validator("ssh_user_password", "new_enable_secret")(_no_space_secret)


class RejectRequest(StrictModel):
    reason: Annotated[str, StringConstraints(max_length=200, pattern=r"^[A-Za-z0-9 _.,:/()@+=!'-]*$")] = ""
