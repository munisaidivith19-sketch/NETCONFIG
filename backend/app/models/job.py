"""Job request models. Credentials appear ONLY in RunRequest (POST /jobs/{id}/run), never in JobCreate."""

from typing import Annotated

from pydantic import Field, SecretStr, StringConstraints, field_validator, model_validator

from .common import ObjectIdStr, StrictModel
from .plan import ConfigPlan, DevicePassword, NoteText, _no_space_secret
from .wizards import BootstrapSpec, LinkSpec

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


JobKind = str  # "push" | "multi" | "link" | "bootstrap"
MAX_DEVICES = 20


class JobCreate(StrictModel):
    """One of four shapes (also used by POST /jobs/preview):

    - push:      device_id + plan            one device
    - multi:     device_ids + plan           the same plan (VLANs, ports) on 2–20 switches, one after another
    - link:      link                        both ends of a router link, applied and confirmed together
    - bootstrap: device_id + bootstrap       first-time setup over the serial / lab console
    """

    device_id: ObjectIdStr | None = None
    device_ids: list[ObjectIdStr] | None = Field(default=None, min_length=2, max_length=MAX_DEVICES)
    plan: ConfigPlan | None = None
    link: LinkSpec | None = None
    bootstrap: BootstrapSpec | None = None
    stop_on_failure: bool = True  # multi: do not continue to the next switch after a failed one
    note: NoteText = ""

    @model_validator(mode="after")
    def _shape(self):
        given = {k for k in ("device_id", "device_ids", "plan", "link", "bootstrap") if getattr(self, k) is not None}
        shapes = {"push": {"device_id", "plan"}, "multi": {"device_ids", "plan"}, "link": {"link"},
                  "bootstrap": {"device_id", "bootstrap"}}
        if given not in shapes.values():
            raise ValueError("give device_id + plan, device_ids + plan, link, or device_id + bootstrap")
        if self.device_ids and len(set(self.device_ids)) != len(self.device_ids):
            raise ValueError("each device may be listed only once")
        return self

    @property
    def kind(self) -> JobKind:
        if self.link:
            return "link"
        if self.bootstrap:
            return "bootstrap"
        return "multi" if self.device_ids else "push"


class DeviceLogin(StrictModel):
    """A different login for one device of a multi-device or link job."""

    device_id: ObjectIdStr
    username: LoginUser
    password: LoginSecret
    enable_secret: LoginSecret | None = None

    _check_login = field_validator("password", "enable_secret")(_no_control)


class RunRequest(StrictModel):
    """Device login (and the plan's own secrets) for one run. Held in memory only, never stored.

    The login is required for SSH. A console (serial / lab console) of a new device often has no login,
    so it may be left out there.
    """

    username: LoginUser | None = None
    password: LoginSecret | None = None
    enable_secret: LoginSecret | None = None
    logins: list[DeviceLogin] = Field(default_factory=list, max_length=MAX_DEVICES)  # per-device overrides
    ssh_user_password: DevicePassword | None = None  # password of the local user the plan creates
    new_enable_secret: DevicePassword | None = None  # enable secret the plan sets

    _check_login = field_validator("password", "enable_secret")(_no_control)
    _check_plan = field_validator("ssh_user_password", "new_enable_secret")(_no_space_secret)

    @model_validator(mode="after")
    def _pairs(self):
        if (self.username is None) != (self.password is None):
            raise ValueError("give both a username and a password, or neither (console without login)")
        if len({lg.device_id for lg in self.logins}) != len(self.logins):
            raise ValueError("one login per device")
        return self

    def login_for(self, device_id: str) -> tuple[str | None, SecretStr | None, SecretStr | None]:
        for lg in self.logins:
            if lg.device_id == device_id:
                return lg.username, lg.password, lg.enable_secret
        return self.username, self.password, self.enable_secret

    def all_secrets(self) -> list[SecretStr]:
        values = [self.password, self.enable_secret, self.ssh_user_password, self.new_enable_secret]
        for lg in self.logins:
            values += [lg.password, lg.enable_secret]
        return [v for v in values if v is not None]


class RejectRequest(StrictModel):
    reason: NoteText = ""
