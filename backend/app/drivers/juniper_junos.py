"""Juniper Junos driver: EX switches and vJunos-switch (ELS syntax) and SRX firewalls. Commands and sources:
docs/drivers/juniper_junos.md. Lines marked [LAB] there are proven on vJunos before the driver is "tested".

Junos is different from the IOS-like OSes in three ways that matter here:
- every command is a full "set" statement, so there are no sub-modes to track;
- changes wait in a private candidate until "commit": a refused line or a failed "commit check" means nothing
  was applied, and "commit confirmed N" rolls back by itself unless confirmed with a second "commit";
- a commit is already persistent, so there is no separate save.

Status: experimental (docs/LAB_TESTING.md, section "Juniper vJunos-switch").
"""

import ipaddress
import re

from ..models.plan import ConfigPlan
from ..security.masking import MASK
from ..security.shacrypt import sha512_crypt
from .base import Check, Kind, ModelInfo, Session, vlan_list
from .common import DriverDefaults, dhcp_interface, dhcp_range, first, logical, secret_value, vlan_rows

CAPABILITIES = {"vlans", "access", "trunk", "svi", "routed_if", "dhcp", "nat", "static", "ospf", "bgp", "ssh",
                "default_gateway"}  # no EIGRP: a Cisco protocol
ERROR_PATTERNS = [r"syntax error", r"^\s*error:", r"unknown command", r"missing argument", r"invalid value",
                  r"is ambiguous", r"commit failed", r"configuration check-out failed", r"not within range",
                  r"invalid interface"]
NAT_RULESET, NAT_RULE, NAT_POLICY = "NCS-NAT", "NCS-NAT-OUT", "NCS-ALLOW-OUT"
BGP_GROUP, BGP_EXPORT = "NCS-EBGP", "NCS-BGP-EXPORT"
SET_LINE = re.compile(r"^set\s")


def quote(text: str) -> str:
    """Junos needs quotes around a value with spaces, and shows it that way in "display set"."""
    return f'"{text}"' if " " in text else text


class JuniperJunos(DriverDefaults):
    os_id = "juniper_junos"
    os_name = "Juniper Junos"
    netmiko_device_type = "juniper_junos"
    capabilities = CAPABILITIES
    cli_syntax = "set"
    config_prompt = r"\[edit[^\]]*\]\s+\S+#"

    def __init__(self, model: ModelInfo):
        self.model = model
        self.flags = model.flags
        self.srx = model.category == "router"

    def normalize_interface(self, name: str) -> str:
        """Junos names are typed as shown (ge-0/0/1). The plan's logical names Vlan10 / Loopback0 stay as they
        are and become irb.10 / lo0.0 in the commands."""
        name = name.strip()
        return name if logical(name) else name.lower()

    def l3(self, name: str) -> str:
        """The logical interface that carries an address: ge-0/0/1 → ge-0/0/1.0, Vlan10 → irb.10."""
        kind = logical(name)
        if kind and kind[0] == "vlan":
            return f"irb.{kind[1]}"
        if kind:
            return f"lo0.{kind[1]}"
        return name if "." in name else f"{name}.0"

    def _ifset(self, name: str) -> str:
        """'set interfaces ... unit N' prefix for an address on this interface."""
        phys, _, unit = self.l3(name).partition(".")
        return f"set interfaces {phys} unit {unit}"

    # ------------------------------------------------------------- review
    def review(self, plan: ConfigPlan) -> tuple[dict[str, str], list[str]]:
        errors, notes = {}, []
        h = plan.hardening
        if h and h.disable_http:
            errors["hardening.disable_http"] = ("Junos removes J-Web with a 'delete' command, which NetConfig "
                                                "Studio never sends; turn this option off and remove it by hand")
        if h and h.login_block:
            errors["hardening.login_block"] = "Junos has no 'login block-for' (it uses login retry-options); " \
                                              "turn this option off"
        if h and h.password_encryption:
            notes.append("Junos always stores passwords hashed, so 'password encryption' needs no command.")
        if plan.ssh:
            if plan.ssh.set_enable_secret:
                errors["ssh.set_enable_secret"] = "Junos has no enable secret: the login class gives the rights"  # noqa: S105  # nosec B105 - a message
            if plan.ssh.regenerate_keys:
                errors["ssh.regenerate_keys"] = "Junos creates its SSH host keys itself"
            notes.append("Junos sets the idle timeout per login class; the VTY timeout is not applied. The user "
                         "gets the 'super-user' class.")
        names = {v.id: v.name for v in plan.vlans}
        for i, v in enumerate(plan.vlans):
            if v.name.lower() == "default":
                errors[f"vlans.{i}.name"] = "'default' is the name of Junos VLAN 1"
        for i, group in enumerate(plan.access):
            if group.port_security:
                errors[f"access.{i}.port_security"] = "port security is not supported by the Junos driver yet"
        for i, t in enumerate(plan.trunks):
            if t.native_vlan not in t.allowed_vlans:
                errors[f"trunks.{i}.native_vlan"] = "on Junos the native VLAN must also be an allowed VLAN"
        for i, s in enumerate(plan.svis):
            if s.vlan not in names:
                errors[f"svis.{i}.vlan"] = "add this VLAN to the plan: Junos links the IRB to the VLAN by its name"
        if plan.nat and not self.srx:
            errors["nat"] = "NAT is an SRX firewall feature; EX switches do not do NAT"
        for i, pool in enumerate(plan.dhcp):
            if dhcp_interface(plan, pool) is None:
                errors[f"dhcp.{i}.network"] = ("add the VLAN interface or routed interface of this subnet to the "
                                               "plan: Junos serves DHCP per interface")
            elif not dhcp_range(pool)[2]:
                notes.append(f"DHCP pool {pool.name}: Junos takes one address range per pool, so only the largest "
                             f"free block is used ({' – '.join(dhcp_range(pool)[:2])}).")
        if plan.dhcp and self.srx:
            notes.append("SRX: the security zone of each DHCP interface must allow 'host-inbound-traffic "
                         "system-services dhcp'.")
        r = plan.routing
        if r and r.ospf:
            in_ospf = {oi.interface for oi in r.ospf.interfaces}
            for i, p in enumerate(r.ospf.passive_interfaces):
                if p not in in_ospf:
                    errors[f"routing.ospf.passive_interfaces.{i}"] = ("on Junos a passive interface must also be "
                                                                       "in the OSPF interface list")
            if r.ospf.process_id != 1:
                notes.append("Junos runs one OSPF instance; the process ID is not used.")
        if r and r.ospf and r.bgp and r.ospf.router_id != r.bgp.router_id:
            errors["routing.bgp.router_id"] = "Junos has one router ID: use the same one for OSPF and BGP"
        for i, line in enumerate(plan.custom_commands):
            if not line.startswith("set "):
                errors[f"custom_commands.{i}"] = "on Junos custom commands must be 'set' statements"
        if plan.nat and self.srx:
            notes.append("SRX: the NAT interfaces are put into the 'trust' and 'untrust' security zones and a "
                         "trust → untrust permit policy is added.")
        return errors, notes

    # ------------------------------------------------------------ generate
    def generate(self, plan: ConfigPlan, kind: Kind) -> list[str]:
        self._check_features(plan)
        out: list[str] = []
        if plan.basic:
            out.append(f"set system host-name {plan.basic.hostname}")
            if plan.basic.domain:
                out.append(f"set system domain-name {plan.basic.domain}")
        if plan.hardening and plan.hardening.banner:
            out.append(f'set system login message "{plan.hardening.banner}"')
        if plan.ssh:
            s = plan.ssh
            pw = secret_value(s.password, kind)  # Junos gets a $6$ hash, never the password itself
            hashed = MASK if kind == "preview" else f'"{sha512_crypt(pw)}"'
            out += [f"set system login user {s.username} class super-user",
                    f"set system login user {s.username} authentication encrypted-password {hashed}",
                    "set system services ssh protocol-version v2"]
        names = {v.id: v.name for v in plan.vlans}
        for v in plan.vlans:
            out.append(f"set vlans {v.name} vlan-id {v.id}")
        for group in plan.access:
            for name in group.interfaces:
                if group.description:
                    out.append(f"set interfaces {name} description {quote(group.description)}")
                eth = f"set interfaces {name} unit 0 family ethernet-switching"
                out += [f"{eth} interface-mode access", f"{eth} vlan members {group.vlan}"]
                if group.portfast:
                    out.append(f"set protocols rstp interface {name} edge")
        for t in plan.trunks:
            if t.description:
                out.append(f"set interfaces {t.interface} description {quote(t.description)}")
            eth = f"set interfaces {t.interface} unit 0 family ethernet-switching"
            out.append(f"{eth} interface-mode trunk")
            out += [f"{eth} vlan members {item}" for item in vlan_list(t.allowed_vlans).split(",")]
            out.append(f"set interfaces {t.interface} native-vlan-id {t.native_vlan}")
        for s in plan.svis:
            if s.description:
                out.append(f"set interfaces irb unit {s.vlan} description {quote(s.description)}")
            out += [f"set interfaces irb unit {s.vlan} family inet address {s.ip}",
                    f"set vlans {names[s.vlan]} l3-interface irb.{s.vlan}"]
        for r in plan.interfaces:
            if r.description:
                phys = self.l3(r.interface).split(".")[0]
                target = f"{phys} unit {self.l3(r.interface).split('.')[1]}" if logical(r.interface) else phys
                out.append(f"set interfaces {target} description {quote(r.description)}")
            out.append(f"{self._ifset(r.interface)} family inet address {r.ip}")
        self._dhcp(plan, out)
        self._nat(plan, out)
        for st in plan.statics:
            prefix = ipaddress.IPv4Network(st.prefix)
            hop = st.next_hop or self.l3(st.interface)
            out.append(f"set routing-options static route {prefix} next-hop {hop}")
            if st.distance:
                out.append(f"set routing-options static route {prefix} preference {st.distance}")
        if plan.default_gateway:
            out.append(f"set routing-options static route 0.0.0.0/0 next-hop {plan.default_gateway}")
        self._routing(plan, out)
        out += list(plan.custom_commands)
        return out

    def _dhcp(self, plan: ConfigPlan, out: list[str]) -> None:
        for pool in plan.dhcp:
            low, high, _ = dhcp_range(pool)
            base = f"set access address-assignment pool {pool.name} family inet"
            out += [f"{base} network {ipaddress.IPv4Network(pool.network)}",
                    f"{base} range R1 low {low}", f"{base} range R1 high {high}",
                    f"{base} dhcp-attributes router {pool.default_router}"]
            out += [f"{base} dhcp-attributes name-server {dns}" for dns in pool.dns_servers]
            if pool.domain:
                out.append(f"{base} dhcp-attributes domain-name {pool.domain}")
            out += [f"{base} dhcp-attributes maximum-lease-time {pool.lease_days * 86400}",
                    f"set system services dhcp-local-server group {pool.name} interface "
                    f"{self.l3(dhcp_interface(plan, pool))}"]

    def _nat(self, plan: ConfigPlan, out: list[str]) -> None:
        n = plan.nat
        if not n:
            return
        out.append(f"set security zones security-zone untrust interfaces {self.l3(n.outside_interface)}")
        out += [f"set security zones security-zone trust interfaces {self.l3(i)}" for i in n.inside_interfaces]
        rs = f"set security nat source rule-set {NAT_RULESET}"
        out += [f"{rs} from zone trust", f"{rs} to zone untrust"]
        out += [f"{rs} rule {NAT_RULE} match source-address {ipaddress.IPv4Network(net)}"
                for net in n.inside_networks]
        out.append(f"{rs} rule {NAT_RULE} then source-nat interface")
        pol = f"set security policies from-zone trust to-zone untrust policy {NAT_POLICY}"
        out += [f"{pol} match source-address any", f"{pol} match destination-address any",
                f"{pol} match application any", f"{pol} then permit"]

    def _routing(self, plan: ConfigPlan, out: list[str]) -> None:
        r = plan.routing
        if not r:
            return
        if r.ospf:
            o = r.ospf
            out.append(f"set routing-options router-id {o.router_id}")
            passive = set(o.passive_interfaces)
            for oi in o.interfaces:
                line = f"set protocols ospf area {ipaddress.IPv4Address(oi.area)} interface {self.l3(oi.interface)}"
                out.append(line)
                if oi.interface in passive:
                    out.append(f"{line} passive")
        if r.bgp:
            b = r.bgp
            if not r.ospf:
                out.append(f"set routing-options router-id {b.router_id}")
            out.append(f"set routing-options autonomous-system {b.asn}")
            grp = f"set protocols bgp group {BGP_GROUP}"
            out.append(f"{grp} type external")
            for nb in b.neighbors:
                out.append(f"{grp} neighbor {nb.ip} peer-as {nb.remote_as}")
                if nb.description:
                    out.append(f"{grp} neighbor {nb.ip} description {quote(nb.description)}")
            if b.networks:
                pol = f"set policy-options policy-statement {BGP_EXPORT}"
                out += [f"{pol} term NETS from route-filter {ipaddress.IPv4Network(n)} exact" for n in b.networks]
                out += [f"{pol} term NETS then accept", f"{pol} term REJECT then reject", f"{grp} export {BGP_EXPORT}"]

    # -------------------------------------------------------------- verify
    def verify_commands(self, plan: ConfigPlan) -> list[str]:
        cmds = ["show configuration | display set"]
        if plan.svis or plan.interfaces:
            cmds.append("show interfaces terse")
        if plan.routing and plan.routing.ospf:
            cmds.append("show ospf neighbor")
        if plan.routing and plan.routing.bgp:
            cmds.append("show bgp summary")
        return cmds

    def check(self, plan: ConfigPlan, outputs: dict[str, str]) -> list[Check]:
        """Every statement of the plan must be in the committed configuration ("display set" prints exactly
        the statements, one per line). One check per part of the configuration."""
        shown = outputs.get("show configuration | display set")
        if shown is None:
            return [Check("output of 'show configuration | display set'", False, "command output missing")]
        committed = {line.strip() for line in shown.splitlines() if SET_LINE.match(line.strip())}
        groups: dict[str, list[str]] = {}
        own = self.generate(plan, "preview")
        for line in own[:len(own) - len(plan.custom_commands)]:
            if MASK in line:
                continue  # the device shows a hash, never the value typed
            groups.setdefault(_group(line), [])
            if line not in committed:
                groups[_group(line)].append(line)
        checks = [Check(f"committed: {g}", not missing, "missing: " + "; ".join(missing[:2]) if missing else "")
                  for g, missing in groups.items()]
        if plan.ssh:
            user = f"set system login user {plan.ssh.username} authentication encrypted-password "
            checks.append(Check(f"local user {plan.ssh.username} has a password",
                                any(line.startswith(user) for line in committed)))
        if plan.svis or plan.interfaces:
            terse = parse_terse(outputs.get("show interfaces terse", ""))
            for name, cidr in [(f"Vlan{s.vlan}", s.ip) for s in plan.svis] + \
                              [(x.interface, x.ip) for x in plan.interfaces]:
                row = terse.get(self.l3(name))
                checks.append(Check(f"{self.l3(name)} address {cidr}", bool(row and cidr in row["addresses"]),
                                    "not listed" if row is None else ", ".join(row["addresses"]) or "no address"))
                if row:
                    up = row["admin"] == "up" and row["link"] == "up"
                    checks.append(Check(f"{self.l3(name)} up/up", up, f"{row['admin']}/{row['link']}",
                                        required=False))
        if plan.routing and plan.routing.ospf:
            full = len(re.findall(r"\bFull\b", outputs.get("show ospf neighbor", "")))
            checks.append(Check("OSPF neighbours Full", full > 0, f"{full} Full", required=False))
        if plan.routing and plan.routing.bgp:
            out = outputs.get("show bgp summary", "")
            for nb in plan.routing.bgp.neighbors:
                up = bool(re.search(rf"^{re.escape(nb.ip)}\s.*\bEstab", out, re.M))
                checks.append(Check(f"BGP {nb.ip} established", up, required=False))
        return checks

    # -------------------------------------------------------- push support
    def denylist(self) -> list[tuple[tuple[str, ...], str]]:
        # Only the push engine commits, rolls back or leaves the private session. "delete" is denied globally.
        return [(("commit",), "commit"), (("rollback",), "rollback"), (("load",), "load"),
                (("deactivate",), "deactivate"), (("exit",), "exit"), (("quit",), "quit"), (("top",), "top"),
                (("edit",), "edit"), (("request",), "request"), (("start", "shell"), "start shell"), (("run",), "run"),
                (("replace",), "replace"),
                (("rename",), "rename"), (("copy",), "copy"), (("insert",), "insert"), (("wildcard",), "wildcard"),
                # A configuration group applies its settings anywhere, past the management-port checks.
                (("set", "groups"), "set groups"), (("set", "apply-groups"), "set apply-groups"),
                # Event policies and scripts run commands later, past this list (Phase 5B security review).
                (("set", "event-options"), "set event-options"), (("set", "system", "scripts"), "set system scripts")]

    def error_patterns(self) -> list[str]:
        return list(ERROR_PATTERNS)

    def info_patterns(self) -> list[str]:
        return [r"^\s*warning:"]

    def save_command(self) -> str | None:
        return None  # a commit is already saved

    def rollback_strategy(self) -> str:
        return "commit_confirmed"

    def session(self, plan: ConfigPlan, name: str) -> Session:
        """docs/drivers/juniper_junos.md section 1."""
        return Session(strategy="commit_confirmed", begin="configure private",
                       check=("commit check",), arm=(f"commit confirmed {plan.revert_minutes}",),
                       discard=("rollback 0",),
                       confirm=("commit",), confirm_in_config="configure private",
                       revert=("rollback 1", "commit"), revert_in_config="configure private",
                       configure="configure private", applies_immediately=False)

    def management_interface(self, outputs: dict[str, str], mgmt_ip: str) -> str | None:
        for name, row in parse_terse(outputs.get("show interfaces terse", "")).items():
            if any(a.split("/")[0] == mgmt_ip for a in row["addresses"]):
                return name
        return None

    def backup_command(self) -> str:
        return "show configuration | display set"

    def management_commands(self) -> list[str]:
        return ["show interfaces terse"]

    def prompts(self, command: str) -> list[tuple[str, str]] | None:
        # commit / rollback answer slowly and print "#"-lines: wait for the "[edit]" prompt, not the echo.
        return [] if command.startswith(("commit", "rollback")) else None

    # ------------------------------------------------------------ discovery
    def facts_commands(self) -> list[str]:
        return ["show version", "show chassis hardware"]

    def parse_facts(self, outputs: dict[str, str]) -> dict:
        v = outputs.get("show version", "")
        return {"model": first(r"^Model:\s*(\S+)", v), "version": first(r"^Junos:\s*(\S+)", v),
                "hostname": first(r"^Hostname:\s*(\S+)", v),
                "serial": first(r"^Chassis\s+(?:\S+\s+)?(\S+)\s+\S+", outputs.get("show chassis hardware", ""))}

    def vlan_commands(self) -> list[str]:
        return [] if self.srx else ["show vlans"]

    def parse_vlans(self, outputs: dict[str, str]) -> list[dict]:
        """ELS 'show vlans': Routing instance, VLAN name, Tag, Interfaces [LAB: confirm the columns]."""
        return vlan_rows(outputs.get("show vlans", ""), r"^\s*\S+\s+(?P<name>[A-Za-z0-9_.-]+)\s+(?P<id>\d+)\b")

    def neighbor_commands(self) -> list[str]:
        return ["show lldp neighbors"]

    def parse_neighbors(self, outputs: dict[str, str]) -> list[dict]:
        """'show lldp neighbors': Local Interface, Parent Interface, Chassis Id, Port info, System Name."""
        out = []
        for m in re.finditer(r"^(\S+)\s+(\S+)\s+([0-9a-f]{2}(?::[0-9a-f]{2}){5})\s+(\S+)\s+(\S+)\s*$",
                             outputs.get("show lldp neighbors", ""), re.M | re.I):
            out.append({"local": m.group(1), "remote": m.group(5), "port": m.group(4), "ip": None,
                        "protocol": "lldp"})
        return out


def _group(line: str) -> str:
    w = line.split()
    if w[1] == "interfaces" and len(w) > 2:
        return f"interface {w[2]}" if w[2] != "irb" else f"interface irb.{w[4]}"
    if w[1] in ("protocols", "security", "routing-options", "policy-options") and len(w) > 2:
        return f"{w[1]} {w[2]}"
    if w[1] == "access":
        return f"DHCP pool {w[4]}"
    return " ".join(w[1:3])


def parse_terse(text: str) -> dict[str, dict]:
    """'show interfaces terse': Interface Admin Link Proto Local [Remote]. A logical interface may list more
    addresses on following lines that start with spaces."""
    rows: dict[str, dict] = {}
    current = None
    for line in text.splitlines():
        if not line.strip() or line.startswith("Interface"):
            continue
        parts = line.split()
        if not line[0].isspace():
            current = parts[0]
            rows[current] = {"admin": parts[1] if len(parts) > 1 else "", "link": parts[2] if len(parts) > 2 else "",
                             "addresses": []}
            parts = parts[3:]
        if current is None:
            continue
        rows[current]["addresses"] += [p for p in parts if re.fullmatch(r"\d+\.\d+\.\d+\.\d+/\d+", p)]
    return rows
