"""ConfigPlan – what the engineer asks for, independent of vendor (CLAUDE.md 6, 8.4).

Every free-text field uses an allowlist of characters. That is the main defence against command
injection into the device CLI: no newline (a new command), no ``;`` or ``|`` (command chaining on some
CLIs), no ``#`` (our banner delimiter) and no ``^`` (the classic ``^C`` banner delimiter).
"""

from typing import Annotated, Literal

from pydantic import Field, SecretStr, StringConstraints, field_validator, model_validator

from .common import StrictModel

SAFE_TEXT = r"^[A-Za-z0-9 _.,:/()@+=-]*$"
# No "?" anywhere: typed at an IOS prompt it opens context help instead of being entered.
SAFE_BANNER = r"^[A-Za-z0-9 _.,:/()@+=!'-]*$"

Hostname = Annotated[str, StringConstraints(min_length=1, max_length=63,
                                            pattern=r"^[A-Za-z]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")]
Domain = Annotated[str, StringConstraints(
    max_length=253, pattern=r"^([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$")]
Description = Annotated[str, StringConstraints(max_length=80, pattern=SAFE_TEXT)]
BannerText = Annotated[str, StringConstraints(min_length=1, max_length=240, pattern=SAFE_BANNER)]
Name32 = Annotated[str, StringConstraints(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")]
DeviceUser = Annotated[str, StringConstraints(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")]
IfName = Annotated[str, StringConstraints(min_length=2, max_length=48, pattern=r"^[A-Za-z0-9][A-Za-z0-9/.:-]*$")]
# [0-9], not \d: the regex engine treats \d as any Unicode digit (e.g. full-width digits).
IPv4 = Annotated[str, StringConstraints(max_length=15, pattern=r"^[0-9]{1,3}(\.[0-9]{1,3}){3}$")]
IPv4Cidr = Annotated[str, StringConstraints(max_length=18, pattern=r"^[0-9]{1,3}(\.[0-9]{1,3}){3}/[0-9]{1,2}$")]
VlanId = Annotated[int, Field(ge=1, le=4094)]
CustomCommand = Annotated[str, StringConstraints(min_length=1, max_length=200,
                                                 pattern=r"^[A-Za-z0-9 _.,:/()@+=*!-]+$")]
DevicePassword = Annotated[SecretStr, Field(min_length=8, max_length=64)]


def _no_space_secret(value: SecretStr | None) -> SecretStr | None:
    if value is not None:
        raw = value.get_secret_value()
        if any(c.isspace() for c in raw) or any(c in raw for c in "#?;|\"'^"):
            raise ValueError("must not contain spaces or any of # ? ; | \" ' ^")
    return value


class Basic(StrictModel):
    hostname: Hostname
    domain: Domain | None = None


class Ssh(StrictModel):
    """SSH v2 with a local admin user. The secrets are optional here: a preview masks them anyway, and
    the wizard asks for them together with the device login only when the job is run (CLAUDE.md 6)."""

    username: DeviceUser
    password: DevicePassword | None = None
    set_enable_secret: bool = False
    enable_secret: DevicePassword | None = None
    rsa_modulus: Literal[2048, 3072, 4096] = 2048
    regenerate_keys: bool = False
    vty_timeout_minutes: int = Field(default=10, ge=1, le=60)

    _check_password = field_validator("password", "enable_secret")(_no_space_secret)


class LoginBlock(StrictModel):
    block_seconds: int = Field(default=120, ge=1, le=3600)
    attempts: int = Field(default=5, ge=1, le=20)
    within_seconds: int = Field(default=60, ge=1, le=3600)


class Hardening(StrictModel):
    password_encryption: bool = True
    disable_http: bool = True
    login_block: LoginBlock | None = Field(default_factory=LoginBlock)
    banner: BannerText | None = None


class Vlan(StrictModel):
    id: VlanId
    name: Name32


class PortSecurity(StrictModel):
    maximum: int = Field(default=1, ge=1, le=64)
    violation: Literal["protect", "restrict", "shutdown"] = "shutdown"
    sticky: bool = False


class AccessPorts(StrictModel):
    interfaces: list[IfName] = Field(min_length=1, max_length=96)
    vlan: VlanId
    description: Description | None = None
    portfast: bool = True
    port_security: PortSecurity | None = None


class Trunk(StrictModel):
    interface: IfName
    allowed_vlans: list[VlanId] = Field(min_length=1, max_length=500)
    native_vlan: VlanId = 1
    description: Description | None = None


class Svi(StrictModel):
    vlan: VlanId
    ip: IPv4Cidr
    description: Description | None = None


class RoutedInterface(StrictModel):
    interface: IfName
    ip: IPv4Cidr
    description: Description | None = None


class ExcludedRange(StrictModel):
    start: IPv4
    end: IPv4 | None = None


class DhcpPool(StrictModel):
    name: Name32
    network: IPv4Cidr
    default_router: IPv4
    dns_servers: list[IPv4] = Field(default_factory=list, max_length=8)
    domain: Domain | None = None
    lease_days: int = Field(default=1, ge=1, le=365)
    excluded: list[ExcludedRange] = Field(default_factory=list, max_length=10)


class Nat(StrictModel):
    inside_interfaces: list[IfName] = Field(min_length=1, max_length=16)
    outside_interface: IfName
    inside_networks: list[IPv4Cidr] = Field(min_length=1, max_length=16)


class StaticRoute(StrictModel):
    prefix: IPv4Cidr
    next_hop: IPv4 | None = None
    interface: IfName | None = None
    distance: int | None = Field(default=None, ge=1, le=255)

    @model_validator(mode="after")
    def _one_target(self):
        if (self.next_hop is None) == (self.interface is None):
            raise ValueError("give either a next hop or an exit interface")
        return self


class OspfInterface(StrictModel):
    interface: IfName
    area: int = Field(default=0, ge=0, le=4294967295)


class Ospf(StrictModel):
    process_id: int = Field(default=1, ge=1, le=65535)
    router_id: IPv4
    interfaces: list[OspfInterface] = Field(min_length=1, max_length=64)
    passive_interfaces: list[IfName] = Field(default_factory=list, max_length=64)


class Eigrp(StrictModel):
    asn: int = Field(ge=1, le=65535)
    router_id: IPv4
    networks: list[IPv4Cidr] = Field(min_length=1, max_length=64)
    passive_interfaces: list[IfName] = Field(default_factory=list, max_length=64)


class BgpNeighbor(StrictModel):
    ip: IPv4
    remote_as: int = Field(ge=1, le=4294967295)
    description: Description | None = None


class Bgp(StrictModel):
    asn: int = Field(ge=1, le=4294967295)
    router_id: IPv4
    neighbors: list[BgpNeighbor] = Field(min_length=1, max_length=32)
    networks: list[IPv4Cidr] = Field(default_factory=list, max_length=64)


class Routing(StrictModel):
    ospf: Ospf | None = None
    eigrp: Eigrp | None = None
    bgp: Bgp | None = None


class ConfigPlan(StrictModel):
    basic: Basic | None = None
    ssh: Ssh | None = None
    hardening: Hardening | None = None
    vlans: list[Vlan] = Field(default_factory=list, max_length=256)
    access: list[AccessPorts] = Field(default_factory=list, max_length=48)
    trunks: list[Trunk] = Field(default_factory=list, max_length=48)
    svis: list[Svi] = Field(default_factory=list, max_length=64)
    interfaces: list[RoutedInterface] = Field(default_factory=list, max_length=48)
    dhcp: list[DhcpPool] = Field(default_factory=list, max_length=32)
    nat: Nat | None = None
    statics: list[StaticRoute] = Field(default_factory=list, max_length=64)
    routing: Routing | None = None
    custom_commands: list[CustomCommand] = Field(default_factory=list, max_length=50)
    save: bool = True
    revert_minutes: int = Field(default=10, ge=2, le=120)

    def features(self) -> list[str]:
        """Capability names this plan uses (matches the OS driver capability matrix)."""
        used = []
        for name, present in [
            ("vlans", self.vlans), ("access", self.access), ("trunk", self.trunks), ("svi", self.svis),
            ("routed_if", self.interfaces), ("dhcp", self.dhcp), ("nat", self.nat), ("static", self.statics),
            ("ospf", self.routing and self.routing.ospf), ("eigrp", self.routing and self.routing.eigrp),
            ("bgp", self.routing and self.routing.bgp), ("ssh", self.ssh),
        ]:
            if present:
                used.append(name)
        return used

    def without_secrets(self) -> dict:
        """JSON-safe copy for storage: every SecretStr is removed, never just masked."""
        data = self.model_dump(mode="json")
        if data.get("ssh"):
            data["ssh"].pop("password", None)
            data["ssh"].pop("enable_secret", None)
        return data


class PreviewRequest(StrictModel):
    device_id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{24}$")] | None = None
    model_id: Annotated[str, StringConstraints(max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$")] | None = None
    plan: ConfigPlan

    @model_validator(mode="after")
    def _target(self):
        if (self.device_id is None) == (self.model_id is None):
            raise ValueError("give either device_id or model_id")
        return self
