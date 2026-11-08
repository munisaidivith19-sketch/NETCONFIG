"""Cross-field checks on a ConfigPlan (CLAUDE.md 8.4). Errors are keyed by field path, e.g. "vlans.0.id".

The Pydantic model already enforces types, lengths, list sizes and allowed characters. This module
checks what needs the whole plan or the target model: IP maths with ``ipaddress``, duplicates,
overlaps, VLAN rules, interface names against the model's port pattern, and driver capabilities.
"""

import ipaddress
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from ..drivers.base import ModelInfo, vlan_list
from ..models.plan import ConfigPlan

RESERVED_VLANS = range(1002, 1006)
LOGICAL_IF = re.compile(r"^(Vlan([1-9][0-9]{0,3})|Loopback[0-9]{1,10})$")
MAX_TRUNK_LIST_CHARS = 240

FEATURE_PATHS = {
    "vlans": "vlans", "access": "access", "trunk": "trunks", "svi": "svis", "routed_if": "interfaces",
    "dhcp": "dhcp", "nat": "nat", "static": "statics", "ospf": "routing.ospf", "eigrp": "routing.eigrp",
    "bgp": "routing.bgp", "ssh": "ssh",
}
FEATURE_LABELS = {
    "vlans": "VLANs", "access": "Access ports", "trunk": "Trunks", "svi": "VLAN interfaces (SVIs)",
    "routed_if": "Routed interfaces", "dhcp": "DHCP server", "nat": "NAT", "static": "Static routes",
    "ospf": "OSPF", "eigrp": "EIGRP", "bgp": "BGP", "ssh": "SSH",
}


@dataclass
class Result:
    errors: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    unsupported: list[dict] = field(default_factory=list)

    def error(self, path: str, message: str) -> None:
        self.errors.setdefault(path, message)

    @property
    def ok(self) -> bool:
        return not self.errors


# ----------------------------------------------------------------- normalise
def normalize_interfaces(plan: ConfigPlan, normalize: Callable[[str], str]) -> ConfigPlan:
    """Expand abbreviations ('gi1/0/1' → 'GigabitEthernet1/0/1') everywhere an interface name appears."""
    data = plan.model_dump()  # python mode keeps SecretStr objects
    for g in data["access"]:
        g["interfaces"] = [normalize(n) for n in g["interfaces"]]
    for key in ("trunks", "interfaces"):
        for item in data[key]:
            item["interface"] = normalize(item["interface"])
    for st in data["statics"]:
        if st["interface"]:
            st["interface"] = normalize(st["interface"])
    if data["nat"]:
        data["nat"]["inside_interfaces"] = [normalize(n) for n in data["nat"]["inside_interfaces"]]
        data["nat"]["outside_interface"] = normalize(data["nat"]["outside_interface"])
    routing = data["routing"] or {}
    if routing.get("ospf"):
        for oi in routing["ospf"]["interfaces"]:
            oi["interface"] = normalize(oi["interface"])
    for proto in ("ospf", "eigrp"):
        if routing.get(proto):
            routing[proto]["passive_interfaces"] = [normalize(n) for n in routing[proto]["passive_interfaces"]]
    return ConfigPlan.model_validate(data)


# ------------------------------------------------------------------- helpers
def _host(r: Result, path: str, value: str) -> ipaddress.IPv4Address | None:
    try:
        ip = ipaddress.IPv4Address(value)
    except ValueError:
        r.error(path, "not a valid IPv4 address")
        return None
    if ip.is_multicast or ip.is_loopback or ip.is_unspecified or ip.is_reserved or ip.is_link_local \
            or ip == ipaddress.IPv4Address("255.255.255.255"):
        r.error(path, "must be a normal unicast address")
        return None
    return ip


def _interface_ip(r: Result, path: str, cidr: str) -> ipaddress.IPv4Interface | None:
    try:
        iface = ipaddress.IPv4Interface(cidr)
    except ValueError:
        r.error(path, "not a valid address/prefix (example 10.0.10.1/24)")
        return None
    if _host(r, path, str(iface.ip)) is None:
        return None
    net = iface.network
    if net.prefixlen <= 30 and iface.ip == net.network_address:
        r.error(path, f"{iface.ip} is the network address of {net}; use a host address")
        return None
    if net.prefixlen <= 30 and iface.ip == net.broadcast_address:
        r.error(path, f"{iface.ip} is the broadcast address of {net}")
        return None
    return iface


def _network(r: Result, path: str, cidr: str) -> ipaddress.IPv4Network | None:
    try:
        return ipaddress.IPv4Network(cidr, strict=True)
    except ValueError:
        try:
            fixed = ipaddress.IPv4Network(cidr, strict=False)
        except ValueError:
            r.error(path, "not a valid network (example 10.0.20.0/24)")
            return None
        r.error(path, f"host bits are set; did you mean {fixed}?")
        return None


def _router_id(r: Result, path: str, value: str) -> None:
    try:
        ip = ipaddress.IPv4Address(value)
    except ValueError:
        r.error(path, "router ID must look like an IPv4 address (a.b.c.d)")
        return
    if ip.is_unspecified or ip.is_multicast or ip == ipaddress.IPv4Address("255.255.255.255"):
        r.error(path, "router ID cannot be 0.0.0.0, multicast or broadcast")


class _Ports:
    """Interface names checked against the model's port pattern (plus VLAN/loopback interfaces where allowed)."""

    def __init__(self, model: ModelInfo):
        self.model = model
        pattern = model.port_pattern or "^$"
        self.regex = re.compile(pattern)
        self.example = ", ".join(model.port_examples[:2])

    def check(self, r: Result, path: str, name: str, logical: bool = False) -> bool:
        if logical and LOGICAL_IF.match(name):
            if name.startswith("Vlan") and self.model.category not in ("switch", "l3switch"):
                r.error(path, f"{self.model.name} has no VLAN interfaces; use a physical port or a Loopback")
                return False
            return True
        if name and self.regex.fullmatch(name):
            return True
        hint = f" (for example {self.example})" if self.example else ""
        r.error(path, f"{name} is not a port on {self.model.name}{hint}")
        return False


def _vlan_ref(r: Result, path: str, vid: int) -> None:
    if vid in RESERVED_VLANS:
        r.error(path, "VLANs 1002–1005 are reserved")


# -------------------------------------------------------------------- main
def validate_plan(plan: ConfigPlan, *, model: ModelInfo, capabilities: set[str], os_name: str) -> Result:
    r = Result()
    ports = _Ports(model)

    for feature in plan.features():
        if feature not in capabilities:
            msg = f"{FEATURE_LABELS[feature]} is not supported on {model.name} ({os_name})"
            r.unsupported.append({"feature": feature, "message": msg})
            r.error(FEATURE_PATHS[feature], msg)

    # SSH needs a hostname and domain name before RSA keys can be generated.
    if plan.ssh and not (plan.basic and plan.basic.domain):
        r.error("basic.domain" if plan.basic else "basic", "SSH needs a hostname and a domain name (for its RSA keys)")

    # VLANs
    seen_vlans: dict[int, int] = {}
    for i, v in enumerate(plan.vlans):
        if v.id == 1:
            r.error(f"vlans.{i}.id", "VLAN 1 is the default VLAN and always exists; use 2–4094")
        elif v.id in RESERVED_VLANS:
            r.error(f"vlans.{i}.id", "VLANs 1002–1005 are reserved")
        elif v.id in seen_vlans:
            r.error(f"vlans.{i}.id", f"duplicate VLAN {v.id} (also vlans.{seen_vlans[v.id]})")
        seen_vlans.setdefault(v.id, i)
    defined = set(seen_vlans) | {1}

    # Physical ports may appear in only one role.
    used_ports: dict[str, str] = {}

    def claim(path: str, name: str) -> None:
        if name in used_ports:
            r.error(path, f"{name} is already used at {used_ports[name]}")
        else:
            used_ports[name] = path

    for g_i, g in enumerate(plan.access):
        _vlan_ref(r, f"access.{g_i}.vlan", g.vlan)
        if g.vlan not in defined and g.vlan not in RESERVED_VLANS:
            r.warnings.append(f"VLAN {g.vlan} (access.{g_i}) is not in this plan; "
                              "the switch creates it without a name.")
        for p_i, name in enumerate(g.interfaces):
            path = f"access.{g_i}.interfaces.{p_i}"
            if ports.check(r, path, name):
                claim(path, name)

    for t_i, t in enumerate(plan.trunks):
        if ports.check(r, f"trunks.{t_i}.interface", t.interface):
            claim(f"trunks.{t_i}.interface", t.interface)
        _vlan_ref(r, f"trunks.{t_i}.native_vlan", t.native_vlan)
        for v_i, vid in enumerate(t.allowed_vlans):
            _vlan_ref(r, f"trunks.{t_i}.allowed_vlans.{v_i}", vid)
        if len(set(t.allowed_vlans)) != len(t.allowed_vlans):
            r.error(f"trunks.{t_i}.allowed_vlans", "list a VLAN only once")
        if len(vlan_list(t.allowed_vlans)) > MAX_TRUNK_LIST_CHARS:
            r.error(f"trunks.{t_i}.allowed_vlans", "too many separate VLAN ranges for one command; use ranges")
        if t.native_vlan not in t.allowed_vlans:
            r.warnings.append(f"Native VLAN {t.native_vlan} is not in the allowed list of {t.interface}.")

    # Layer 3 addresses: valid hosts, no overlaps.
    subnets: list[tuple[str, ipaddress.IPv4Network]] = []
    own_ips: dict[str, str] = {}

    def add_subnet(path: str, iface: ipaddress.IPv4Interface) -> None:
        for other_path, net in subnets:
            if iface.network.overlaps(net):
                r.error(path, f"{iface.network} overlaps {net} ({other_path})")
                return
        subnets.append((path, iface.network))
        own_ips[str(iface.ip)] = path

    seen_svi: dict[int, int] = {}
    for s_i, s in enumerate(plan.svis):
        _vlan_ref(r, f"svis.{s_i}.vlan", s.vlan)
        if s.vlan in seen_svi:
            r.error(f"svis.{s_i}.vlan", f"VLAN {s.vlan} already has an interface (svis.{seen_svi[s.vlan]})")
        seen_svi.setdefault(s.vlan, s_i)
        if s.vlan not in defined:
            r.warnings.append(f"Vlan{s.vlan} comes up only when VLAN {s.vlan} exists and has an active port.")
        iface = _interface_ip(r, f"svis.{s_i}.ip", s.ip)
        if iface:
            add_subnet(f"svis.{s_i}.ip", iface)

    for i_i, it in enumerate(plan.interfaces):
        path = f"interfaces.{i_i}.interface"
        if ports.check(r, path, it.interface, logical=True) and not LOGICAL_IF.match(it.interface):
            claim(path, it.interface)
        iface = _interface_ip(r, f"interfaces.{i_i}.ip", it.ip)
        if iface:
            add_subnet(f"interfaces.{i_i}.ip", iface)
    if_ips = {f"Vlan{s.vlan}": s.ip for s in plan.svis} | {it.interface: it.ip for it in plan.interfaces}

    # DHCP
    pool_names: dict[str, int] = {}
    pool_nets: list[tuple[str, ipaddress.IPv4Network]] = []
    for p_i, pool in enumerate(plan.dhcp):
        base = f"dhcp.{p_i}"
        key = pool.name.lower()
        if key in pool_names:
            r.error(f"{base}.name", f"duplicate pool name (also dhcp.{pool_names[key]})")
        pool_names.setdefault(key, p_i)
        net = _network(r, f"{base}.network", pool.network)
        if net is None:
            continue
        for other, onet in pool_nets:
            if net.overlaps(onet):
                r.error(f"{base}.network", f"overlaps {onet} ({other})")
        pool_nets.append((f"{base}.network", net))
        gw = _host(r, f"{base}.default_router", pool.default_router)
        if gw is not None:
            if gw not in net or gw in (net.network_address, net.broadcast_address):
                r.error(f"{base}.default_router", f"the gateway must be a host address inside {net}")
            elif str(gw) not in own_ips and not any(gw in n for _, n in subnets):
                r.warnings.append(f"No interface in this plan is in {net}; pool {pool.name} works only if the "
                                  "device already has an address there.")
        for d_i, dns in enumerate(pool.dns_servers):
            _host(r, f"{base}.dns_servers.{d_i}", dns)
        for e_i, ex in enumerate(pool.excluded):
            start = _host(r, f"{base}.excluded.{e_i}.start", ex.start)
            end = _host(r, f"{base}.excluded.{e_i}.end", ex.end) if ex.end else start
            if start is None or end is None:
                continue
            if start not in net or end not in net:
                r.error(f"{base}.excluded.{e_i}", f"the excluded range must be inside {net}")
            elif int(end) < int(start):
                r.error(f"{base}.excluded.{e_i}.end", "the end must not be before the start")

    # NAT
    if plan.nat:
        n = plan.nat
        for i, name in enumerate(n.inside_interfaces):
            ports.check(r, f"nat.inside_interfaces.{i}", name, logical=True)
            if name == n.outside_interface:
                r.error(f"nat.inside_interfaces.{i}", "an interface cannot be both inside and outside")
        ports.check(r, "nat.outside_interface", n.outside_interface, logical=True)
        for i, cidr in enumerate(n.inside_networks):
            _network(r, f"nat.inside_networks.{i}", cidr)

    # Static routes
    seen_routes: dict[tuple, int] = {}
    for s_i, st in enumerate(plan.statics):
        net = _network(r, f"statics.{s_i}.prefix", st.prefix)
        if st.next_hop:
            hop = _host(r, f"statics.{s_i}.next_hop", st.next_hop)
            if hop is not None and str(hop) in own_ips:
                r.error(f"statics.{s_i}.next_hop", "the next hop is this device's own address")
        if st.interface:
            ports.check(r, f"statics.{s_i}.interface", st.interface, logical=True)
        key = (str(net), st.next_hop or st.interface)
        if net is not None and key in seen_routes:
            r.error(f"statics.{s_i}.prefix", f"duplicate route (also statics.{seen_routes[key]})")
        seen_routes.setdefault(key, s_i)

    # Routing protocols
    rt = plan.routing
    if rt and rt.ospf:
        o = rt.ospf
        _router_id(r, "routing.ospf.router_id", o.router_id)
        seen: set[str] = set()
        for i, oi in enumerate(o.interfaces):
            path = f"routing.ospf.interfaces.{i}.interface"
            if oi.interface in seen:
                r.error(path, "listed twice")
            seen.add(oi.interface)
            if oi.interface not in if_ips:
                r.error(path, "OSPF needs this interface's IP address: add it under SVIs or routed interfaces")
        for i, name in enumerate(o.passive_interfaces):
            ports.check(r, f"routing.ospf.passive_interfaces.{i}", name, logical=True)
        if plan.revert_minutes < 5:
            r.warnings.append("OSPF needs time to form neighbours; a revert timer of 5 minutes or more is safer.")
    if rt and rt.eigrp:
        e = rt.eigrp
        _router_id(r, "routing.eigrp.router_id", e.router_id)
        for i, cidr in enumerate(e.networks):
            _network(r, f"routing.eigrp.networks.{i}", cidr)
        for i, name in enumerate(e.passive_interfaces):
            ports.check(r, f"routing.eigrp.passive_interfaces.{i}", name, logical=True)
    if rt and rt.bgp:
        b = rt.bgp
        _router_id(r, "routing.bgp.router_id", b.router_id)
        seen_nb: set[str] = set()
        for i, nb in enumerate(b.neighbors):
            path = f"routing.bgp.neighbors.{i}.ip"
            if _host(r, path, nb.ip) is None:
                continue
            if nb.ip in seen_nb:
                r.error(path, "duplicate neighbour")
            elif nb.ip in own_ips:
                r.error(path, "the neighbour address is this device's own address")
            seen_nb.add(nb.ip)
            if nb.remote_as == b.asn:
                r.warnings.append(f"Neighbour {nb.ip} is in the same AS (iBGP); only eBGP is tested.")
        for i, cidr in enumerate(b.networks):
            _network(r, f"routing.bgp.networks.{i}", cidr)
        if plan.revert_minutes < 5:
            r.warnings.append("BGP sessions can take minutes to come up; a revert timer of 5 minutes or more is safer.")

    if plan.custom_commands:
        r.warnings.append("Custom commands are sent as typed. Check them carefully; they are written to the audit log.")
    return r
