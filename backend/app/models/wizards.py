"""Inputs of the Phase 3B wizards. They only describe intent; services/wizards.py turns them into normal
ConfigPlans (one per device), so every plan still goes through the same validation, denylist and drivers.

No field here holds a secret: the new admin password and enable secret are given at run time.
"""

from typing import Literal

from pydantic import Field

from .common import ObjectIdStr, StrictModel
from .plan import Description, DeviceUser, Domain, Hostname, IfName, IPv4, IPv4Cidr, VlanId


class BootstrapMgmt(StrictModel):
    vlan: VlanId = 1  # switches: the management VLAN interface (SVI)
    interface: IfName | None = None  # routers: the port that carries management, e.g. GigabitEthernet0/0
    ip: IPv4Cidr  # the device's new management address, e.g. 10.0.0.2/24
    gateway: IPv4 | None = None


class BootstrapSpec(StrictModel):
    """First-time setup over a console: just enough for safe SSH management afterwards."""

    hostname: Hostname
    domain: Domain  # needed for the RSA keys
    mgmt: BootstrapMgmt
    admin_username: DeviceUser
    rsa_modulus: Literal[2048, 3072, 4096] = 2048
    vty_timeout_minutes: int = Field(default=10, ge=1, le=60)
    hardening: bool = True  # service password-encryption, no web server, login block-for
    revert_minutes: int = Field(default=10, ge=2, le=120)


class LinkEnd(StrictModel):
    device_id: ObjectIdStr
    interface: IfName
    router_id: IPv4 | None = None  # OSPF / EIGRP / BGP
    asn: int | None = Field(default=None, ge=1, le=4294967295)  # BGP: this side's AS


class LinkSpec(StrictModel):
    """A point-to-point link between two routers (or Layer 3 switches), configured on both sides at once."""

    a: LinkEnd
    b: LinkEnd
    subnet: IPv4Cidr  # a /30 or /31 network, e.g. 10.255.0.0/30
    protocol: Literal["none", "ospf", "eigrp", "bgp"] = "ospf"
    ospf_process_id: int = Field(default=1, ge=1, le=65535)
    ospf_area: int = Field(default=0, ge=0, le=4294967295)
    eigrp_asn: int | None = Field(default=None, ge=1, le=65535)
    description: Description | None = None  # default: "link to <other router>"
    revert_minutes: int = Field(default=10, ge=5, le=120)  # routing needs time; both sides share the window
