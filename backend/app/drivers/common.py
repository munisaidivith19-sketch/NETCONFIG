"""Helpers shared by the Phase 4 drivers (Arista EOS, Juniper Junos, Aruba AOS-CX). All pure functions."""

import ipaddress
import re

from ..models.plan import ConfigPlan, DhcpPool
from ..security.masking import MASK
from .base import Check, Kind, UnsupportedFeature


def secret_value(value, kind: Kind, what: str = "ssh.password") -> str:
    """A secret inside a generated command: masked in a preview, the real value only when pushing."""
    if kind == "preview":
        return MASK
    if value is None:
        raise ValueError(f"{what} is required to push this plan")
    return value.get_secret_value()


class DriverDefaults:
    """What most drivers share: the "not supported on <OS>" check and push hooks that do nothing.
    A driver overrides a hook only when its OS needs it (Cisco: the archive for the revert timer, RSA keys)."""

    os_name = ""
    capabilities: set[str] = set()

    def _check_features(self, plan: ConfigPlan) -> None:
        for feature in plan.features():
            if feature not in self.capabilities:
                raise UnsupportedFeature(feature, self.os_name)

    def config_dump_commands(self) -> set[str]:
        return {self.backup_command()}

    def precheck_commands(self, plan: ConfigPlan) -> list[str]:
        return []

    def adapt_commands(self, plan, commands, outputs):
        return commands, []

    def rollback_setup(self, running_config: str) -> list[str]:
        return []


_IF_SPLIT = re.compile(r"^([A-Za-z-]+?)\s*([0-9][0-9/.:]*)$")


def normalize_by_types(name: str, types: list[str]) -> str:
    """'et1' → 'Ethernet1', 'vlan 10' → 'Vlan10'. Only a unique prefix expands, so nothing is guessed."""
    m = _IF_SPLIT.match(name.strip())
    if not m:
        return name.strip()
    prefix, number = m.group(1).lower(), m.group(2)
    exact = [t for t in types if t.lower() == prefix]
    if exact:
        return exact[0] + number
    matches = [t for t in types if t.lower().startswith(prefix)]
    return matches[0] + number if len(matches) == 1 else name.strip()


def logical(name: str) -> tuple[str, int] | None:
    """The plan's vendor-neutral logical names: ('vlan', 10) for 'Vlan10', ('loopback', 0) for 'Loopback0'."""
    m = re.fullmatch(r"(Vlan|Loopback)([0-9]+)", name)
    return (m.group(1).lower(), int(m.group(2))) if m else None


def dhcp_range(pool: DhcpPool) -> tuple[str, str, bool]:
    """The largest run of addresses a pool can hand out: the subnet's hosts minus the excluded addresses and the
    default router. Junos, EOS and AOS-CX take one range per pool rather than Cisco's excluded addresses.
    Returns (low, high, whole) where whole=False means other free addresses outside the range are not used."""
    net = ipaddress.IPv4Network(pool.network)
    # Hosts: everything but the network and broadcast address (a /31 or /32 has no such reserved addresses).
    first, last = int(net.network_address), int(net.broadcast_address)
    if net.prefixlen < 31:
        first, last = first + 1, last - 1
    # Taken addresses as intervals, so a /8 pool costs a few steps, not 16 million (Phase 4D review).
    router = int(ipaddress.IPv4Address(pool.default_router))
    taken = [(router, router)]
    for ex in pool.excluded:
        a = int(ipaddress.IPv4Address(ex.start))
        taken.append((a, int(ipaddress.IPv4Address(ex.end)) if ex.end else a))
    runs, nxt = [], first  # nxt: the lowest address not yet known to be taken
    for a, b in sorted(taken):
        if a > nxt and nxt <= last:
            runs.append((nxt, min(a - 1, last)))
        nxt = max(nxt, b + 1)
    if nxt <= last:
        runs.append((nxt, last))
    if not runs:
        raise ValueError(f"DHCP pool {pool.name} has no free addresses")
    low, high = max(runs, key=lambda r: r[1] - r[0])
    return str(ipaddress.IPv4Address(low)), str(ipaddress.IPv4Address(high)), len(runs) == 1


def dhcp_interface(plan: ConfigPlan, pool: DhcpPool) -> str | None:
    """The plan's SVI or routed interface whose subnet is the pool's network (the interface that serves it)."""
    net = ipaddress.IPv4Network(pool.network)
    candidates = [(f"Vlan{s.vlan}", s.ip) for s in plan.svis] + [(r.interface, r.ip) for r in plan.interfaces]
    return next((name for name, cidr in candidates if ipaddress.IPv4Interface(cidr).network == net), None)


def section_checks(commands: list[str], run: dict, hidden: frozenset[str] = frozenset()) -> list[Check]:
    """'Was every line kept?' for IOS-like configs (EOS, AOS-CX): each top-level command must be in the running
    configuration, and each indented line must be in the body of the section it was typed under (nested
    sections are flattened into their top-level section by parse_running_config). One check per section.
    Lines that the running configuration never shows are skipped: "no ..." (defaults are hidden), "exit",
    lines that carry a secret (the device shows a hash instead) and ``hidden``: the OS's own default lines."""
    top = set(run["top"])
    bodies: dict[str, set[str]] = {}
    for head, body in run["sections"]:
        bodies.setdefault(head, set()).update(body.splitlines())
    checks: dict[str, list[str]] = {}
    head = None
    for cmd in commands:
        text = cmd.strip()
        if MASK in text:
            continue
        if not cmd.startswith(" "):
            head = text
            checks.setdefault(head, [])
            if text not in top:
                checks[head].append(text)
            continue
        if head is None or text.startswith(("no ", "undo ")) or text in ("exit", "exit-address-family", "end", "quit") \
                or text in hidden:
            continue
        if text not in bodies.get(head, set()):
            checks[head].append(text)
    return [Check(f"configured: {h}", not missing, "missing: " + "; ".join(missing[:3]) if missing else "")
            for h, missing in checks.items()]


def vlan_rows(text: str, pattern: str) -> list[dict]:
    """[{'id': 10, 'name': 'Staff'}] from a VLAN table. ``pattern`` captures the VLAN ID and name (in either
    order, as named groups ``id`` and ``name``)."""
    rows = {}
    for m in re.finditer(pattern, text or "", re.M):
        vid = int(m.group("id"))
        if 1 <= vid <= 4094:
            rows.setdefault(vid, m.group("name")[:32])
    return [{"id": vid, "name": name} for vid, name in sorted(rows.items())]


def first(pattern: str, text: str, flags: int = re.M) -> str | None:
    m = re.search(pattern, text or "", flags)
    return m.group(1).strip() if m else None
