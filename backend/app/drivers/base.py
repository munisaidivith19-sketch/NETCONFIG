"""Driver interface (CLAUDE.md 7). One driver per OS family; models are catalog data.

Drivers are pure: they turn a validated ConfigPlan into commands and parse ``show`` output into
checks. They never open connections or touch the database, which is what makes golden-file tests
possible.
"""

import re
from dataclasses import dataclass, field
from typing import Literal, Protocol

from ..models.plan import ConfigPlan

Kind = Literal["preview", "push"]  # preview: secrets masked; push: real secrets (never stored)


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str = ""
    required: bool = True  # informational checks (e.g. a BGP session still coming up) do not fail a push


@dataclass(frozen=True)
class ModelInfo:
    """What a driver needs to know about the target model (from the catalog)."""

    id: str
    name: str
    category: str
    port_pattern: str = ""
    port_examples: tuple[str, ...] = ()
    flags: dict = field(default_factory=dict)

    @classmethod
    def from_doc(cls, doc: dict) -> "ModelInfo":
        return cls(id=doc["_id"], name=doc.get("name", doc["_id"]), category=doc.get("category", ""),
                   port_pattern=doc.get("port_pattern", ""), port_examples=tuple(doc.get("port_examples", [])),
                   flags=dict(doc.get("driver_flags", {})))


class UnsupportedFeature(Exception):
    def __init__(self, feature: str, os_name: str, detail: str = ""):
        self.feature = feature
        self.os_name = os_name
        super().__init__(detail or f"{feature} is not supported on {os_name}")


def vlan_list(ids: list[int]) -> str:
    """10,20,30-35 – runs of three or more become a range; the order is always ascending."""
    ids = sorted(set(ids))
    parts, i = [], 0
    while i < len(ids):
        j = i
        while j + 1 < len(ids) and ids[j + 1] == ids[j] + 1:
            j += 1
        if j - i >= 2:
            parts.append(f"{ids[i]}-{ids[j]}")
        else:
            parts.extend(str(v) for v in ids[i:j + 1])
        i = j + 1
    return ",".join(parts)


def expand_vlan_list(text: str) -> set[int]:
    out: set[int] = set()
    for part in re.split(r"[,\s]+", text.strip()):
        if not part or part.lower() in {"none", "all"}:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            if a.isdigit() and b.isdigit():
                out.update(range(int(a), int(b) + 1))
        elif part.isdigit():
            out.add(int(part))
    return out


class Driver(Protocol):
    os_id: str
    os_name: str
    netmiko_device_type: str
    capabilities: set[str]
    model: ModelInfo

    def generate(self, plan: ConfigPlan, kind: Kind) -> list[str]: ...
    def verify_commands(self, plan: ConfigPlan) -> list[str]: ...
    def check(self, plan: ConfigPlan, outputs: dict[str, str]) -> list[Check]: ...
    def error_patterns(self) -> list[str]: ...
    def save_command(self) -> str | None: ...
    def rollback_strategy(self) -> str: ...
    def management_interface(self, outputs: dict[str, str], mgmt_ip: str) -> str | None: ...
    def session_steps(self, plan: ConfigPlan) -> dict[str, list[str]]: ...
    def normalize_interface(self, name: str) -> str: ...
