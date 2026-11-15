"""Helpers shared by the Phase 4 drivers (Arista EOS, Juniper Junos, Aruba AOS-CX). All pure functions."""

import ipaddress
import re

from ..models.plan import ConfigPlan, DhcpPool
from ..security.masking import MASK
from .base import Check

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
    taken = {ipaddress.IPv4Address(pool.default_router)}
    for ex in pool.excluded:
        a = ipaddress.IPv4Address(ex.start)
        b = ipaddress.IPv4Address(ex.end) if ex.end else a
        taken.update(ipaddress.IPv4Address(i) for i in range(int(a), int(b) + 1))
    runs, start, prev = [], None, None
    for host in net.hosts():
        if host in taken:
            if start is not None:
                runs.append((start, prev))
            start = None
        elif start is None:
            start = host
        prev = host
    if start is not None:
        runs.append((start, prev))
    if not runs:
        raise ValueError(f"DHCP pool {pool.name} has no free addresses")
    low, high = max(runs, key=lambda r: int(r[1]) - int(r[0]))
    return str(low), str(high), len(runs) == 1


def dhcp_interface(plan: ConfigPlan, pool: DhcpPool) -> str | None:
    """The plan's SVI or routed interface whose subnet is the pool's network (the interface that serves it)."""
    net = ipaddress.IPv4Network(pool.network)
    candidates = [(f"Vlan{s.vlan}", s.ip) for s in plan.svis] + [(r.interface, r.ip) for r in plan.interfaces]
    return next((name for name, cidr in candidates if ipaddress.IPv4Interface(cidr).network == net), None)


def section_checks(commands: list[str], run: dict) -> list[Check]:
    """'Was every line kept?' for IOS-like configs (EOS, AOS-CX): each top-level command must be in the running
    configuration, and each indented line must be in the body of the section it was typed under (nested
    sections are flattened into their top-level section by parse_running_config). One check per section.
    Lines that the running configuration never shows are skipped: "no ..." (defaults are hidden), "exit",
    and lines that carry a secret (the device shows a hash instead)."""
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
                or "********" in text:
            continue
        if text not in bodies.get(head, set()):
            checks[head].append(text)
    return [Check(f"configured: {h}", not missing, "missing: " + "; ".join(missing[:3]) if missing else "")
            for h, missing in checks.items()]


def first(pattern: str, text: str, flags: int = re.M) -> str | None:
    m = re.search(pattern, text or "", flags)
    return m.group(1).strip() if m else None
