"""Device inventory models. A device never stores passwords (CLAUDE.md 6, 8.3)."""

import ipaddress
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from .common import StrictModel

DeviceName = Annotated[str, StringConstraints(min_length=1, max_length=63,
                                              pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")]
Location = Annotated[str, StringConstraints(max_length=64, pattern=r"^[A-Za-z0-9 _.,:/()-]*$")]
Tag = Annotated[str, StringConstraints(min_length=1, max_length=24, pattern=r"^[a-z0-9][a-z0-9-]{0,23}$")]
ModelId = Annotated[str, StringConstraints(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$")]

PRODUCTION_TAG = "production"

# Telnet is allowed only to lab/emulator consoles on loopback or RFC1918 addresses (CLAUDE.md 8.5).
LAB_NETWORKS = [ipaddress.ip_network(n) for n in
                ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "::1/128")]


def is_lab_address(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return any(addr in net for net in LAB_NETWORKS)


class Connection(StrictModel):
    method: Literal["ssh", "serial", "telnet_lab", "none"] = "ssh"
    port: int | None = Field(default=None, ge=1, le=65535)
    serial_port: Annotated[str, StringConstraints(pattern=r"^COM[1-9][0-9]{0,2}$")] | None = None
    baud: Literal[9600, 19200, 38400, 57600, 115200] | None = None

    @model_validator(mode="after")
    def _defaults(self):
        if self.method == "ssh" and self.port is None:
            self.port = 22
        if self.method == "telnet_lab" and self.port is None:
            self.port = 23
        if self.method == "serial":
            if not self.serial_port:
                raise ValueError("serial_port (for example COM3) is required for the serial console")
            self.baud = self.baud or 9600
            self.port = None
        else:
            self.serial_port = None
            self.baud = None
        if self.method == "none":
            self.port = None
        return self


class DeviceCreate(StrictModel):
    name: DeviceName
    model_id: ModelId
    mgmt_ip: str | None = Field(default=None, max_length=45)
    connection: Connection = Field(default_factory=Connection)
    location: Location = ""
    tags: list[Tag] = Field(default_factory=list, max_length=10)

    @field_validator("mgmt_ip")
    @classmethod
    def _ip(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        try:
            addr = ipaddress.ip_address(value)
        except ValueError as exc:
            raise ValueError("not a valid IPv4 or IPv6 address") from exc
        if addr.is_unspecified or addr.is_multicast:
            raise ValueError("cannot be an unspecified or multicast address")
        return str(addr)

    @field_validator("tags")
    @classmethod
    def _tags(cls, tags: list[str]) -> list[str]:
        return sorted(set(tags))

    @model_validator(mode="after")
    def _connection_rules(self):
        method = self.connection.method
        if method in ("ssh", "telnet_lab") and not self.mgmt_ip:
            raise ValueError("mgmt_ip is required for SSH or lab-console connections")
        if method == "telnet_lab" and not is_lab_address(self.mgmt_ip):
            raise ValueError("telnet is only allowed to lab consoles on loopback or RFC1918 addresses")
        return self


class DeviceUpdate(StrictModel):
    name: DeviceName | None = None
    model_id: ModelId | None = None
    mgmt_ip: str | None = Field(default=None, max_length=45)
    connection: Connection | None = None
    location: Location | None = None
    tags: list[Tag] | None = Field(default=None, max_length=10)


class DeviceOut(BaseModel):
    id: str
    name: str
    model_id: str
    model_name: str | None
    brand: str | None
    category: str | None
    os_id: str | None
    os_name: str | None
    support: str | None
    capabilities: list[str]
    mgmt_ip: str | None
    connection: dict
    location: str
    tags: list[str]
    production: bool
    status: dict
    created_at: datetime | None
    updated_at: datetime | None
