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


@dataclass(frozen=True)
class Session:
    """How a driver changes the configuration safely (CLAUDE.md 8.5 "Rollback"). The push engine follows these
    commands without knowing the vendor:

    start (exec mode, e.g. AOS-CX "checkpoint auto 10") → begin (enter config) → plan commands → arm (config
    mode, e.g. Junos "commit confirmed 10") → leave config → verify → confirm → save.
    On a problem: discard (nothing committed yet) or revert (undo a live change).

    ``timer``: the device itself undoes an unconfirmed change when the time runs out (Cisco revert timer, Junos
    commit confirmed, EOS commit timer, AOS-CX auto checkpoint). Then a lost connection is safe. With a timer but
    no ``revert`` (AOS-CX) a failed change is undone when the timer ends. Without a timer (strategy
    "backup_restore") nothing undoes the change automatically: a failure needs a person (MANUAL ACTION).
    """

    strategy: str  # revert_timer | commit_confirmed | session_timer | checkpoint | backup_restore
    begin: str  # enters config mode for the change
    start: tuple[str, ...] = ()  # exec mode, before begin (starts the timer on AOS-CX)
    revert: tuple[str, ...] = ()  # undo a live change now
    confirm: tuple[str, ...] = ()  # keep the change (cancels the timer)
    arm: tuple[str, ...] = ()  # config mode, after the plan commands (starts the timer on commit-based OSes)
    discard: tuple[str, ...] = ()  # config mode: drop changes that were never committed
    leave: tuple[str, ...] = ()  # config mode: sent before leaving it (AOS-CX "end": Netmiko misses sub-contexts)
    confirm_in_config: str | None = None  # confirm must be sent inside this config session (Junos "commit")
    revert_in_config: str | None = None  # revert must be sent inside this config session (Junos "rollback 1")
    configure: str = "configure terminal"  # a plain config session for rollback_setup()
    timer: bool = True
    applies_immediately: bool = True  # False: commands wait in a candidate until "arm" commits them


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

    cli_syntax: str  # "ios" (interface sub-modes: Cisco, EOS, AOS-CX) | "set" (Junos set commands)
    config_prompt: str  # regex of the config-mode prompt, for commands that need an expect string

    # Config commands. Custom commands must come LAST: planning.custom_audit() relies on it.
    def generate(self, plan: ConfigPlan, kind: Kind) -> list[str]: ...
    def review(self, plan: ConfigPlan) -> tuple[dict[str, str], list[str]]: ...  # (errors by field, warnings)
    def denylist(self) -> list[tuple[tuple[str, ...], str]]: ...  # extra denied commands for this OS (8.5)
    def verify_commands(self, plan: ConfigPlan) -> list[str]: ...
    def check(self, plan: ConfigPlan, outputs: dict[str, str]) -> list[Check]: ...
    def error_patterns(self) -> list[str]: ...
    def info_patterns(self) -> list[str]: ...  # lines that look like errors but are not (e.g. "% Generating keys")
    def save_command(self) -> str | None: ...
    def rollback_strategy(self) -> str: ...
    def management_interface(self, outputs: dict[str, str], mgmt_ip: str) -> str | None: ...
    def session(self, plan: ConfigPlan, name: str) -> Session: ...  # name: unique per change (EOS sessions)
    def normalize_interface(self, name: str) -> str: ...

    # Push engine support. Pure functions too: the engine runs the show commands and passes their outputs in,
    # so services/push.py never contains a vendor's command or output format.
    def backup_command(self) -> str: ...  # the whole running configuration
    def config_dump_commands(self) -> set[str]: ...  # whole-config outputs: never copied into a transcript
    def management_commands(self) -> list[str]: ...  # outputs that management_interface() reads
    def precheck_commands(self, plan: ConfigPlan) -> list[str]: ...  # read before applying, for adapt_commands()
    def adapt_commands(self, plan: ConfigPlan, commands: list[str],
                       outputs: dict[str, str]) -> tuple[list[str], list[str]]: ...  # (commands, notes)
    def prompts(self, command: str) -> list[tuple[str, str]] | None: ...  # (prompt regex, answer) it asks
    def rollback_setup(self, running_config: str) -> list[str]: ...  # config needed before the rollback works
    # Discovery (Phase 4B): read-only commands and parsers for status, model detection and topology.
    def facts_commands(self) -> list[str]: ...
    def parse_facts(self, outputs: dict[str, str]) -> dict: ...  # {"model", "version", "serial", "hostname"}
    def neighbor_commands(self) -> list[str]: ...
    def parse_neighbors(self, outputs: dict[str, str]) -> list[dict]: ...  # [{"local", "remote", "port"}]
