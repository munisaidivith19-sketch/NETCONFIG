"""Cisco IOS / IOS-XE driver. Every command here is documented, with sources, in docs/drivers/cisco_ios.md.

Status: experimental until the lab checklist passes (docs/LAB_TESTING.md).
"""

import ipaddress
import re

from ..models.plan import ConfigPlan
from ..security.masking import MASK
from .base import Check, Kind, ModelInfo, UnsupportedFeature, expand_vlan_list, vlan_list

ALL_CAPABILITIES = {"vlans", "access", "trunk", "svi", "routed_if", "dhcp", "nat", "static", "ospf", "eigrp",
                    "bgp", "ssh"}

# Full interface type names. An abbreviation expands only when exactly one name starts with it.
IF_TYPES = ["GigabitEthernet", "FastEthernet", "TenGigabitEthernet", "TwoGigabitEthernet", "FiveGigabitEthernet",
            "TwentyFiveGigE", "FortyGigabitEthernet", "HundredGigE", "Ethernet", "Vlan", "Loopback", "Port-channel"]
IF_ALIASES = {"tw": "TwoGigabitEthernet", "te": "TenGigabitEthernet", "twe": "TwentyFiveGigE",
              "fo": "FortyGigabitEthernet",
              "hu": "HundredGigE", "po": "Port-channel", "eth": "Ethernet"}
_IF_SPLIT = re.compile(r"^([A-Za-z-]+?)\s*([0-9][0-9/.:]*)$")

ERROR_PATTERNS = [
    r"% Invalid input detected",
    r"% Incomplete command",
    r"% Ambiguous command",
    r"% Unknown command",
    r"% Bad mask",
    r"% Inconsistent address and mask",
    r"overlaps with",
    r"% Invalid VLAN",
    r"Command rejected",
    r"% Error",
]
# Lines that look like errors but are not (docs/drivers/cisco_ios.md section 17).
INFO_PATTERNS = [r"% Access VLAN does not exist\. Creating vlan", r"^%(LINK|LINEPROTO)-", r"% Warning"]

NAT_ACL = "NCS_NAT_INSIDE"
ARCHIVE_DIR = "ncs-archive"


def _mask(net: ipaddress.IPv4Network) -> str:
    return str(net.netmask)


def _wildcard(net: ipaddress.IPv4Network) -> str:
    return str(net.hostmask)


def _addr(cidr: str) -> tuple[str, str]:
    iface = ipaddress.IPv4Interface(cidr)
    return str(iface.ip), str(iface.netmask)


class CiscoIos:
    os_id = "cisco_ios"
    os_name = "Cisco IOS / IOS-XE"
    netmiko_device_type = "cisco_ios"
    capabilities = ALL_CAPABILITIES

    def __init__(self, model: ModelInfo):
        self.model = model
        self.flags = model.flags
        self.layer3_switch = model.category == "l3switch"

    # ---------------------------------------------------------------- names
    def normalize_interface(self, name: str) -> str:
        """'gi1/0/1' → 'GigabitEthernet1/0/1'. Unknown or ambiguous names are returned unchanged
        and then fail the model's port pattern, so nothing is guessed."""
        m = _IF_SPLIT.match(name.strip())
        if not m:
            return name.strip()
        prefix, number = m.group(1).lower(), m.group(2)
        if prefix in IF_ALIASES:
            return IF_ALIASES[prefix] + number
        matches = [t for t in IF_TYPES if t.lower().startswith(prefix)]
        exact = [t for t in matches if t.lower() == prefix]
        if exact:
            return exact[0] + number
        return matches[0] + number if len(matches) == 1 else name.strip()

    # ------------------------------------------------------------- generate
    def generate(self, plan: ConfigPlan, kind: Kind) -> list[str]:
        for feature in plan.features():
            if feature not in self.capabilities:
                raise UnsupportedFeature(feature, self.os_name)
        out: list[str] = []
        self._basic(plan, out)
        self._hardening(plan, out)
        self._ssh(plan, kind, out)
        for v in plan.vlans:
            out += [f"vlan {v.id}", f" name {v.name}"]
        if self.layer3_switch and (plan.svis or plan.interfaces or plan.statics or plan.routing):
            out.append("ip routing")
        self._access(plan, out)
        self._trunks(plan, out)
        for s in plan.svis:
            ip, mask = _addr(s.ip)
            out.append(f"interface Vlan{s.vlan}")
            if s.description:
                out.append(f" description {s.description}")
            out += [f" ip address {ip} {mask}", " no shutdown"]
        for r in plan.interfaces:
            ip, mask = _addr(r.ip)
            out.append(f"interface {r.interface}")
            if r.description:
                out.append(f" description {r.description}")
            if self.layer3_switch and not r.interface.startswith(("Vlan", "Loopback")):
                out.append(" no switchport")
            out += [f" ip address {ip} {mask}", " no shutdown"]
        self._dhcp(plan, out)
        self._nat(plan, out)
        for st in plan.statics:
            net = ipaddress.IPv4Network(st.prefix)
            line = f"ip route {net.network_address} {_mask(net)} {st.next_hop or st.interface}"
            out.append(f"{line} {st.distance}" if st.distance else line)
        self._routing(plan, out)
        out += list(plan.custom_commands)
        return out

    def _basic(self, plan: ConfigPlan, out: list[str]) -> None:
        if plan.basic:
            out.append(f"hostname {plan.basic.hostname}")
            if plan.basic.domain:
                out.append(f"ip domain name {plan.basic.domain}")

    def _hardening(self, plan: ConfigPlan, out: list[str]) -> None:
        h = plan.hardening
        if not h:
            return
        if h.password_encryption:
            out.append("service password-encryption")
        if h.disable_http:
            out += ["no ip http server", "no ip http secure-server"]
        if h.login_block:
            b = h.login_block
            out.append(f"login block-for {b.block_seconds} attempts {b.attempts} within {b.within_seconds}")
        if h.banner:
            # '#' is the delimiter; validation forbids '#' in the text, so the banner cannot end early.
            out.append(f"banner motd #{h.banner}#")

    def _ssh(self, plan: ConfigPlan, kind: Kind, out: list[str]) -> None:
        s = plan.ssh
        if not s:
            return

        def secret(value, what: str) -> str:
            if kind == "preview":
                return MASK
            if value is None:
                raise ValueError(f"{what} is required to push this plan")
            return value.get_secret_value()

        out.append(f"username {s.username} privilege 15 secret {secret(s.password, 'ssh.password')}")
        if s.set_enable_secret:
            out.append(f"enable secret {secret(s.enable_secret, 'ssh.enable_secret')}")
        # The push engine checks "show crypto key mypubkey rsa" first and only sends this line when there
        # are no keys or regenerate_keys is set (it then answers the replace prompt) – see push.py.
        out.append(f"crypto key generate rsa modulus {s.rsa_modulus}")
        out.append("ip ssh version 2")
        ranges = ["0 4"] + (["5 15"] if int(self.flags.get("vty_lines", 5)) >= 16 else [])
        for r in ranges:
            out += [f"line vty {r}", " login local", " transport input ssh", f" exec-timeout {s.vty_timeout_minutes} 0"]

    def _access(self, plan: ConfigPlan, out: list[str]) -> None:
        keyword = self.flags.get("portfast_keyword", "")
        portfast = "spanning-tree portfast" + (f" {keyword}" if keyword else "")
        for group in plan.access:
            for name in group.interfaces:
                out.append(f"interface {name}")
                if group.description:
                    out.append(f" description {group.description}")
                out += [" switchport mode access", f" switchport access vlan {group.vlan}"]
                ps = group.port_security
                if ps:
                    out += [" switchport port-security", f" switchport port-security maximum {ps.maximum}",
                            f" switchport port-security violation {ps.violation}"]
                    if ps.sticky:
                        out.append(" switchport port-security mac-address sticky")
                if group.portfast:
                    out.append(f" {portfast}")
                out.append(" no shutdown")

    def _trunks(self, plan: ConfigPlan, out: list[str]) -> None:
        for t in plan.trunks:
            out.append(f"interface {t.interface}")
            if t.description:
                out.append(f" description {t.description}")
            if self.flags.get("trunk_encapsulation_cmd"):
                out.append(" switchport trunk encapsulation dot1q")
            out += [" switchport mode trunk", f" switchport trunk native vlan {t.native_vlan}",
                    f" switchport trunk allowed vlan {vlan_list(t.allowed_vlans)}", " no shutdown"]

    def _dhcp(self, plan: ConfigPlan, out: list[str]) -> None:
        for pool in plan.dhcp:
            for ex in pool.excluded:
                out.append(f"ip dhcp excluded-address {ex.start}" + (f" {ex.end}" if ex.end else ""))
            net = ipaddress.IPv4Network(pool.network)
            out += [f"ip dhcp pool {pool.name}", f" network {net.network_address} {_mask(net)}",
                    f" default-router {pool.default_router}"]
            if pool.dns_servers:
                out.append(" dns-server " + " ".join(pool.dns_servers))
            if pool.domain:
                out.append(f" domain-name {pool.domain}")
            out.append(f" lease {pool.lease_days}")

    def _nat(self, plan: ConfigPlan, out: list[str]) -> None:
        n = plan.nat
        if not n:
            return
        out.append(f"ip access-list standard {NAT_ACL}")
        for cidr in n.inside_networks:
            net = ipaddress.IPv4Network(cidr)
            out.append(f" permit {net.network_address} {_wildcard(net)}")
        for name in n.inside_interfaces:
            out += [f"interface {name}", " ip nat inside"]
        out += [f"interface {n.outside_interface}", " ip nat outside",
                f"ip nat inside source list {NAT_ACL} interface {n.outside_interface} overload"]

    def _routing(self, plan: ConfigPlan, out: list[str]) -> None:
        r = plan.routing
        if not r:
            return
        if r.ospf:
            o = r.ospf
            ips = interface_ips(plan)
            out += [f"router ospf {o.process_id}", f" router-id {o.router_id}"]
            for oi in o.interfaces:
                out.append(f" network {ips[oi.interface]} 0.0.0.0 area {oi.area}")
            out += [f" passive-interface {p}" for p in o.passive_interfaces]
        if r.eigrp:
            e = r.eigrp
            out += [f"router eigrp {e.asn}", f" eigrp router-id {e.router_id}"]
            for cidr in e.networks:
                net = ipaddress.IPv4Network(cidr)
                out.append(f" network {net.network_address} {_wildcard(net)}")
            out += [f" passive-interface {p}" for p in e.passive_interfaces]
            out.append(" no auto-summary")
        if r.bgp:
            b = r.bgp
            out += [f"router bgp {b.asn}", f" bgp router-id {b.router_id}"]
            for nb in b.neighbors:
                out.append(f" neighbor {nb.ip} remote-as {nb.remote_as}")
                if nb.description:
                    out.append(f" neighbor {nb.ip} description {nb.description}")
            for cidr in b.networks:
                net = ipaddress.IPv4Network(cidr)
                out.append(f" network {net.network_address} mask {_mask(net)}")

    # ----------------------------------------------------------- verify
    def verify_commands(self, plan: ConfigPlan) -> list[str]:
        f = set(plan.features())
        cmds: list[str] = []
        if plan.basic or plan.hardening or plan.ssh or plan.statics or "eigrp" in f or plan.dhcp or \
                any(g.port_security for g in plan.access):
            cmds.append("show running-config")
        if "ssh" in f:
            cmds.append("show ip ssh")
        if "vlans" in f:
            cmds.append("show vlan brief")
        if "access" in f:
            cmds.append("show interfaces status")
        cmds += [f"show interfaces {t.interface} switchport" for t in plan.trunks]
        if plan.svis or plan.interfaces:
            cmds.append("show ip interface brief")
        if "dhcp" in f:
            cmds.append("show ip dhcp pool")
        if "nat" in f:
            cmds.append("show ip nat statistics")
        if "ospf" in f:
            cmds += ["show ip ospf interface brief", "show ip ospf neighbor"]
        if "eigrp" in f:
            cmds.append("show ip eigrp neighbors")
        if "bgp" in f:
            cmds.append("show ip bgp summary")
        return cmds

    def check(self, plan: ConfigPlan, outputs: dict[str, str]) -> list[Check]:
        checks: list[Check] = []
        run = parse_running_config(outputs.get("show running-config", ""))
        top = run["top"]

        def missing(cmd: str) -> Check:
            return Check(f"output of '{cmd}'", False, "command output missing")

        if "show running-config" in self.verify_commands(plan) and "show running-config" not in outputs:
            return [missing("show running-config")]

        if plan.basic:
            checks.append(Check(f"hostname {plan.basic.hostname}", f"hostname {plan.basic.hostname}" in top))
            if plan.basic.domain:
                d = plan.basic.domain
                checks.append(Check(f"domain {d}", f"ip domain name {d}" in top or f"ip domain-name {d}" in top))
        if plan.hardening:
            h = plan.hardening
            if h.password_encryption:
                checks.append(Check("service password-encryption", "service password-encryption" in top))
            if h.disable_http:
                checks.append(Check("HTTP server disabled", "no ip http server" in top))
                checks.append(Check("HTTPS server disabled", "no ip http secure-server" in top))
            if h.login_block:
                b = h.login_block
                want = f"login block-for {b.block_seconds} attempts {b.attempts} within {b.within_seconds}"
                checks.append(Check("login block-for", want in top))
            if h.banner:
                checks.append(Check("MOTD banner", any(line.startswith("banner motd") for line in top)))
        if plan.ssh:
            ssh_out = outputs.get("show ip ssh")
            if ssh_out is None:
                checks.append(missing("show ip ssh"))
            else:
                checks.append(Check("SSH version 2 enabled", bool(re.search(r"SSH Enabled - version 2\.0", ssh_out)),
                                    _first_line(ssh_out)))
            vty = [body for head, body in run["sections"] if head.startswith("line vty")]
            ok = bool(vty) and all({"transport input ssh", "login local"} <= set(body.splitlines()) for body in vty)
            checks.append(Check("VTY lines: login local, SSH only", ok))
            checks.append(Check(f"local user {plan.ssh.username}",
                                any(line.startswith(f"username {plan.ssh.username} ") for line in top)))
        if plan.vlans:
            checks += self._check_vlans(plan, outputs.get("show vlan brief"))
        if plan.access:
            checks += self._check_access(plan, outputs.get("show interfaces status"), run)
        for t in plan.trunks:
            checks += self._check_trunk(t, outputs.get(f"show interfaces {t.interface} switchport"))
        if plan.svis or plan.interfaces:
            checks += self._check_ip_interfaces(plan, outputs.get("show ip interface brief"))
        if plan.dhcp:
            out = outputs.get("show ip dhcp pool")
            if out is None:
                checks.append(missing("show ip dhcp pool"))
            else:
                pools = set(re.findall(r"^Pool (\S+) :", out, re.M))
                checks += [Check(f"DHCP pool {p.name}", p.name in pools) for p in plan.dhcp]
        if plan.nat:
            checks += self._check_nat(plan, outputs.get("show ip nat statistics"))
        for st in plan.statics:
            net = ipaddress.IPv4Network(st.prefix)
            want = f"ip route {net.network_address} {_mask(net)} {st.next_hop or st.interface}"
            checks.append(Check(f"static route {st.prefix}", any(line.startswith(want) for line in top)))
        if plan.routing:
            checks += self._check_routing(plan, outputs, run)
        return checks

    def _check_vlans(self, plan: ConfigPlan, out: str | None) -> list[Check]:
        if out is None:
            return [Check("output of 'show vlan brief'", False, "command output missing")]
        rows = {int(m.group(1)): (m.group(2), m.group(3))
                for m in re.finditer(r"^(\d+)\s+(\S+)\s+(active|act/\S+|suspended)", out, re.M)}
        checks = []
        for v in plan.vlans:
            row = rows.get(v.id)
            ok = row is not None and row[0] == v.name and row[1] == "active"
            detail = "missing" if row is None else f"name {row[0]}, {row[1]}"
            checks.append(Check(f"VLAN {v.id} {v.name}", ok, detail))
        return checks

    def _check_access(self, plan: ConfigPlan, out: str | None, run: dict) -> list[Check]:
        if out is None:
            return [Check("output of 'show interfaces status'", False, "command output missing")]
        rows = parse_interfaces_status(out, self.normalize_interface)
        checks = []
        for group in plan.access:
            for name in group.interfaces:
                row = rows.get(name)
                ok = row is not None and row["vlan"] == str(group.vlan)
                detail = "not listed" if row is None else f"VLAN {row['vlan']}, {row['status']}"
                checks.append(Check(f"{name} access VLAN {group.vlan}", ok, detail))
                if group.port_security:
                    body = run["interfaces"].get(name, "")
                    checks.append(Check(f"{name} port security", "switchport port-security" in body))
        return checks

    def _check_trunk(self, t, out: str | None) -> list[Check]:
        cmd = f"show interfaces {t.interface} switchport"
        if out is None:
            return [Check(f"output of '{cmd}'", False, "command output missing")]
        mode = re.search(r"^Administrative Mode:\s*(.+)$", out, re.M)
        native = re.search(r"^Trunking Native Mode VLAN:\s*(\d+)", out, re.M)
        allowed_m = re.search(r"^Trunking VLANs Enabled:\s*((?:.+\n?)(?:^[0-9,\-\s]+$\n?)*)", out, re.M)
        allowed = expand_vlan_list(allowed_m.group(1).replace("\n", ",")) if allowed_m else set()
        return [
            Check(f"{t.interface} is a trunk", bool(mode and mode.group(1).strip() == "trunk"),
                  mode.group(1).strip() if mode else "no mode line"),
            Check(f"{t.interface} native VLAN {t.native_vlan}", bool(native and int(native.group(1)) == t.native_vlan),
                  native.group(1) if native else "no native VLAN line"),
            Check(f"{t.interface} allowed VLANs", allowed == set(t.allowed_vlans), vlan_list(sorted(allowed))),
        ]

    def _check_ip_interfaces(self, plan: ConfigPlan, out: str | None) -> list[Check]:
        if out is None:
            return [Check("output of 'show ip interface brief'", False, "command output missing")]
        rows = parse_ip_interface_brief(out, self.normalize_interface)
        checks = []
        wanted = [(f"Vlan{s.vlan}", s.ip) for s in plan.svis] + [(r.interface, r.ip) for r in plan.interfaces]
        for name, cidr in wanted:
            ip = cidr.split("/")[0]
            row = rows.get(name)
            checks.append(Check(f"{name} address {ip}", row is not None and row["ip"] == ip,
                                "not listed" if row is None else row["ip"]))
            if row is not None:
                up = row["status"] == "up" and row["protocol"] == "up"
                checks.append(Check(f"{name} up/up", up, f"{row['status']}/{row['protocol']}", required=False))
        return checks

    def _check_nat(self, plan: ConfigPlan, out: str | None) -> list[Check]:
        if out is None:
            return [Check("output of 'show ip nat statistics'", False, "command output missing")]
        inside = _nat_list(out, "Inside interfaces")
        outside = _nat_list(out, "Outside interfaces")
        norm = self.normalize_interface
        inside, outside = {norm(i) for i in inside}, {norm(i) for i in outside}
        checks = [Check(f"NAT inside {i}", i in inside) for i in plan.nat.inside_interfaces]
        checks.append(Check(f"NAT outside {plan.nat.outside_interface}", plan.nat.outside_interface in outside))
        return checks

    def _check_routing(self, plan: ConfigPlan, outputs: dict[str, str], run: dict) -> list[Check]:
        r = plan.routing
        checks: list[Check] = []
        if r.ospf:
            out = outputs.get("show ip ospf interface brief")
            if out is None:
                checks.append(Check("output of 'show ip ospf interface brief'", False, "command output missing"))
            else:
                rows = {}
                for m in re.finditer(r"^(\S+)\s+(\d+)\s+(\S+)\s+\d+\.\d+\.\d+\.\d+/\d+", out, re.M):
                    rows[self.normalize_interface(m.group(1))] = (int(m.group(2)), m.group(3))
                for oi in r.ospf.interfaces:
                    row = rows.get(oi.interface)
                    ok = row is not None and row[0] == r.ospf.process_id and _area_equal(row[1], oi.area)
                    checks.append(Check(f"OSPF on {oi.interface} area {oi.area}", ok,
                                        "not in OSPF" if row is None else f"process {row[0]} area {row[1]}"))
            nbr = outputs.get("show ip ospf neighbor", "")
            full = len(re.findall(r"\bFULL/", nbr))
            checks.append(Check("OSPF neighbours FULL", full > 0, f"{full} FULL", required=False))
        if r.eigrp:
            body = next((b for h, b in run["sections"] if h == f"router eigrp {r.eigrp.asn}"), None)
            checks.append(Check(f"EIGRP AS {r.eigrp.asn}", body is not None))
            for cidr in r.eigrp.networks:
                net = ipaddress.IPv4Network(cidr)
                want = f"network {net.network_address} {_wildcard(net)}"
                checks.append(Check(f"EIGRP network {cidr}", body is not None and want in body))
            nbrs = outputs.get("show ip eigrp neighbors", "")
            count = len(re.findall(r"^\d+\s+\d+\.\d+\.\d+\.\d+\s", nbrs, re.M))
            checks.append(Check("EIGRP neighbours", count > 0, f"{count} neighbours", required=False))
        if r.bgp:
            out = outputs.get("show ip bgp summary")
            if out is None:
                checks.append(Check("output of 'show ip bgp summary'", False, "command output missing"))
            else:
                ident = re.search(r"BGP router identifier (\S+), local AS number (\d+)", out)
                ok = bool(ident and ident.group(1) == r.bgp.router_id and int(ident.group(2)) == r.bgp.asn)
                checks.append(Check(f"BGP AS {r.bgp.asn} router-id {r.bgp.router_id}", ok,
                                    ident.group(0) if ident else "no BGP identifier line"))
                for nb in r.bgp.neighbors:
                    row = re.search(rf"^{re.escape(nb.ip)}\s+4\s+(\d+)\s.*?(\S+)\s*$", out, re.M)
                    checks.append(Check(f"BGP neighbour {nb.ip} AS {nb.remote_as}",
                                        bool(row and int(row.group(1)) == nb.remote_as),
                                        "not listed" if not row else f"AS {row.group(1)}"))
                    if row:
                        state = row.group(2)
                        checks.append(Check(f"BGP {nb.ip} established", state.isdigit(),
                                            "established" if state.isdigit() else state, required=False))
        return checks

    # --------------------------------------------------------- push support
    def error_patterns(self) -> list[str]:
        return list(ERROR_PATTERNS)

    def info_patterns(self) -> list[str]:
        return list(INFO_PATTERNS)

    def save_command(self) -> str | None:
        return "write memory"

    def rollback_strategy(self) -> str:
        return "revert_timer"

    def session_steps(self, plan: ConfigPlan) -> dict[str, list[str]]:
        """Commands around the change window (docs/drivers/cisco_ios.md section 1)."""
        fs = self.flags.get("archive_fs", "flash:")
        return {
            "archive": ["archive", f" path {fs}{ARCHIVE_DIR}", " maximum 5"],
            "begin": [f"configure terminal revert timer {plan.revert_minutes}"],
            "confirm": ["configure confirm"],
            "revert": ["configure revert now"],
        }

    def management_interface(self, outputs: dict[str, str], mgmt_ip: str) -> str | None:
        rows = parse_ip_interface_brief(outputs.get("show ip interface brief", ""), self.normalize_interface)
        return next((name for name, row in rows.items() if row["ip"] == mgmt_ip), None)


# ----------------------------------------------------------------- parsers
def interface_ips(plan: ConfigPlan) -> dict[str, str]:
    """Interface name → IP address, from the SVIs and routed interfaces in this plan."""
    ips = {f"Vlan{s.vlan}": s.ip.split("/")[0] for s in plan.svis}
    ips.update({r.interface: r.ip.split("/")[0] for r in plan.interfaces})
    return ips


def parse_running_config(text: str) -> dict:
    """Top-level lines, sections (header + indented body) and interface bodies."""
    top: list[str] = []
    sections: list[tuple[str, str]] = []
    head, body = None, []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.startswith("!"):
            continue
        if line[0] != " ":
            if head is not None:
                sections.append((head, "\n".join(body)))
            head, body = line, []
            top.append(line)
        elif head is not None:
            body.append(line.strip())
    if head is not None:
        sections.append((head, "\n".join(body)))
    interfaces = {h.split(" ", 1)[1]: b for h, b in sections if h.startswith("interface ")}
    return {"top": top, "sections": sections, "interfaces": interfaces}


def parse_ip_interface_brief(text: str, normalize) -> dict[str, dict]:
    rows = {}
    pat = re.compile(r"^(\S+)\s+(\S+)\s+(?:YES|NO)\s+\S+\s+(.+?)\s+(up|down)\s*$")
    for line in text.splitlines():
        m = pat.match(line)
        if m and m.group(1) != "Interface":
            rows[normalize(m.group(1))] = {"ip": m.group(2), "status": m.group(3).strip(), "protocol": m.group(4)}
    return rows


def parse_interfaces_status(text: str, normalize) -> dict[str, dict]:
    """'show interfaces status' is fixed-width and the Name column may contain spaces, so the
    columns are cut at the header positions."""
    lines = text.splitlines()
    header = next((i for i, line in enumerate(lines) if line.startswith("Port") and "Status" in line), None)
    if header is None:
        return {}
    h = lines[header]
    s_at, v_at, d_at = h.index("Status"), h.index("Vlan"), h.index("Duplex")
    rows = {}
    for line in lines[header + 1:]:
        if not line.strip():
            continue
        port = line[:s_at].split()[0] if line[:s_at].split() else ""
        status = line[s_at:v_at].split()
        vlan = line[v_at:d_at].split()
        if port:
            rows[normalize(port)] = {"status": status[0] if status else "", "vlan": vlan[0] if vlan else ""}
    return rows


def _nat_list(text: str, title: str) -> list[str]:
    m = re.search(rf"{title}:\s*\n((?:[ \t]+\S.*\n?)*)", text)
    if not m:
        return []
    return [p for p in re.split(r"[,\s]+", m.group(1)) if p]


def _area_equal(shown: str, area: int) -> bool:
    if shown.isdigit():
        return int(shown) == area
    try:
        return int(ipaddress.IPv4Address(shown)) == area
    except ValueError:
        return False


def _first_line(text: str) -> str:
    return text.strip().splitlines()[0] if text.strip() else ""
