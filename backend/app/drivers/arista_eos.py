"""Arista EOS driver. Commands and sources: docs/drivers/arista_eos.md. Lines marked [LAB] there were not read
from an official page and are proven on cEOS-lab before the driver is marked "tested".

Status: experimental (docs/LAB_TESTING.md, section "Arista cEOS-lab").
"""

import ipaddress
import re

from ..models.plan import ConfigPlan
from ..security.masking import MASK
from .base import Check, Kind, ModelInfo, Session, UnsupportedFeature, vlan_list
from .cisco_ios import parse_running_config
from .common import dhcp_interface, dhcp_range, first, logical, normalize_by_types, section_checks

CAPABILITIES = {"vlans", "access", "trunk", "svi", "routed_if", "dhcp", "nat", "static", "ospf", "bgp", "ssh",
                "default_gateway"}  # no EIGRP on EOS
IF_TYPES = ["Ethernet", "Vlan", "Loopback", "Port-Channel", "Management"]
ERROR_PATTERNS = [r"% Invalid input", r"% Incomplete command", r"% Ambiguous command", r"% Unrecognized command",
                  r"% Unavailable command", r"% Error", r"% Maximum number"]
NAT_ACL = "NCS_NAT_INSIDE"


class AristaEos:
    os_id = "arista_eos"
    os_name = "Arista EOS"
    netmiko_device_type = "arista_eos"
    capabilities = CAPABILITIES
    cli_syntax = "ios"
    config_prompt = r"\(config[^)]*\)#"

    def __init__(self, model: ModelInfo):
        self.model = model
        self.flags = model.flags

    def normalize_interface(self, name: str) -> str:
        return normalize_by_types(name, IF_TYPES)

    # ------------------------------------------------------------- review
    def review(self, plan: ConfigPlan) -> tuple[dict[str, str], list[str]]:
        errors, notes = {}, []
        h = plan.hardening
        if h and h.login_block:
            errors["hardening.login_block"] = "Arista EOS has no 'login block-for'; turn this option off"
        if h and h.banner:
            errors["hardening.banner"] = ("an EOS banner is typed in a multi-line editor, which this driver does "
                                          "not drive yet; turn the banner off")
        if h and h.password_encryption:
            notes.append("EOS always stores passwords hashed, so 'password encryption' needs no command.")
        if plan.ssh and plan.ssh.regenerate_keys:
            errors["ssh.regenerate_keys"] = "EOS creates its SSH host keys itself; this driver does not replace them"
        for i, group in enumerate(plan.access):
            if group.port_security:
                errors[f"access.{i}.port_security"] = "port security is not supported by the Arista EOS driver yet"
        domains = {p.domain for p in plan.dhcp if p.domain}
        if len(domains) > 1:
            errors["dhcp"] = "EOS sets one DHCP domain name for the whole server; use the same domain in every pool"
        for i, pool in enumerate(plan.dhcp):
            if len(pool.dns_servers) > 2:
                errors[f"dhcp.{i}.dns_servers"] = "EOS takes at most two DNS servers per subnet"
            if dhcp_interface(plan, pool) is None:
                errors[f"dhcp.{i}.network"] = ("add the VLAN interface or routed interface of this subnet to the "
                                               "plan: EOS enables the DHCP server per interface")
            elif not dhcp_range(pool)[2]:
                notes.append(f"DHCP pool {pool.name}: EOS takes one address range per subnet, so only the largest "
                             f"free block is used ({' – '.join(dhcp_range(pool)[:2])}).")
        if plan.nat:
            notes.append("EOS NAT is set on the outside interface only (no inside marking) and depends on the "
                         "hardware: check the platform supports NAT overload.")
        return errors, notes

    # ------------------------------------------------------------ generate
    def generate(self, plan: ConfigPlan, kind: Kind) -> list[str]:
        for feature in plan.features():
            if feature not in self.capabilities:
                raise UnsupportedFeature(feature, self.os_name)
        out: list[str] = []
        if plan.basic:
            out.append(f"hostname {plan.basic.hostname}")
            if plan.basic.domain:
                out.append(f"dns domain {plan.basic.domain}")
        if plan.hardening and plan.hardening.disable_http:
            out += ["management api http-commands", "   shutdown"]
        self._ssh(plan, kind, out)
        for v in plan.vlans:
            out += [f"vlan {v.id}", f"   name {v.name}"]
        if plan.svis or plan.interfaces or plan.statics or plan.routing:
            out.append("ip routing")  # off by default on EOS
        for group in plan.access:
            for name in group.interfaces:
                out.append(f"interface {name}")
                if group.description:
                    out.append(f"   description {group.description}")
                out += ["   switchport mode access", f"   switchport access vlan {group.vlan}"]
                if group.portfast:
                    out.append("   spanning-tree portfast")
                out.append("   no shutdown")
        for t in plan.trunks:
            out.append(f"interface {t.interface}")
            if t.description:
                out.append(f"   description {t.description}")
            out += ["   switchport mode trunk", f"   switchport trunk native vlan {t.native_vlan}",
                    f"   switchport trunk allowed vlan {vlan_list(t.allowed_vlans)}", "   no shutdown"]
        for s in plan.svis:
            out.append(f"interface Vlan{s.vlan}")
            if s.description:
                out.append(f"   description {s.description}")
            out += [f"   ip address {s.ip}", "   no shutdown"]
        for r in plan.interfaces:
            out.append(f"interface {r.interface}")
            if r.description:
                out.append(f"   description {r.description}")
            if logical(r.interface) is None:
                out.append("   no switchport")
            out += [f"   ip address {r.ip}", "   no shutdown"]
        self._dhcp(plan, out)
        if plan.nat:
            out.append(f"ip access-list standard {NAT_ACL}")
            out += [f"   {(i + 1) * 10} permit {net}" for i, net in enumerate(plan.nat.inside_networks)]
            out += [f"interface {plan.nat.outside_interface}",
                    f"   ip nat source dynamic access-list {NAT_ACL} overload"]
        for st in plan.statics:
            line = f"ip route {ipaddress.IPv4Network(st.prefix)} {st.next_hop or st.interface}"
            out.append(f"{line} {st.distance}" if st.distance else line)
        if plan.default_gateway:
            out.append(f"ip route 0.0.0.0/0 {plan.default_gateway}")
        self._routing(plan, out)
        out += list(plan.custom_commands)
        return out

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

        out.append(f"username {s.username} privilege 15 role network-admin secret {secret(s.password, 'ssh.password')}")
        if s.set_enable_secret:
            out.append(f"enable password {secret(s.enable_secret, 'ssh.enable_secret')}")
        out += ["management ssh", f"   idle-timeout {s.vty_timeout_minutes}"]

    def _dhcp(self, plan: ConfigPlan, out: list[str]) -> None:
        if not plan.dhcp:
            return
        out.append("dhcp server")
        domains = {p.domain for p in plan.dhcp if p.domain}
        if domains:
            out.append(f"   dns domain name ipv4 {domains.pop()}")
        for pool in plan.dhcp:
            low, high, _ = dhcp_range(pool)
            out += [f"   subnet {ipaddress.IPv4Network(pool.network)}", f"      name {pool.name}",
                    f"      range {low} {high}", f"      default-gateway {pool.default_router}"]
            if pool.dns_servers:
                out.append("      dns server " + " ".join(pool.dns_servers))
            out.append(f"      lease time ipv4 {pool.lease_days} days 0 hours 0 minutes")
        for pool in plan.dhcp:
            out += [f"interface {dhcp_interface(plan, pool)}", "   dhcp server ipv4"]

    def _routing(self, plan: ConfigPlan, out: list[str]) -> None:
        r = plan.routing
        if not r:
            return
        if r.ospf:
            o = r.ospf
            ips = {f"Vlan{s.vlan}": s.ip.split("/")[0] for s in plan.svis}
            ips.update({x.interface: x.ip.split("/")[0] for x in plan.interfaces})
            out += [f"router ospf {o.process_id}", f"   router-id {o.router_id}"]
            for oi in o.interfaces:
                out.append(f"   network {ips[oi.interface]}/32 area {ipaddress.IPv4Address(oi.area)}")
            out += [f"   passive-interface {p}" for p in o.passive_interfaces]
        if r.bgp:
            b = r.bgp
            out += [f"router bgp {b.asn}", f"   router-id {b.router_id}"]
            for nb in b.neighbors:
                out.append(f"   neighbor {nb.ip} remote-as {nb.remote_as}")
                if nb.description:
                    out.append(f"   neighbor {nb.ip} description {nb.description}")
            out += [f"   network {ipaddress.IPv4Network(n)}" for n in b.networks]

    # -------------------------------------------------------------- verify
    def verify_commands(self, plan: ConfigPlan) -> list[str]:
        f = set(plan.features())
        cmds = ["show running-config"]
        if "vlans" in f:
            cmds.append("show vlan")
        cmds += [f"show interfaces {t.interface} switchport" for t in plan.trunks]
        if plan.svis or plan.interfaces:
            cmds.append("show ip interface brief")
        if "ospf" in f:
            cmds.append("show ip ospf neighbor")
        if "bgp" in f:
            cmds.append("show ip bgp summary")
        return cmds

    def check(self, plan: ConfigPlan, outputs: dict[str, str]) -> list[Check]:
        if "show running-config" not in outputs:
            return [Check("output of 'show running-config'", False, "command output missing")]
        run = parse_running_config(outputs["show running-config"])
        own = self.generate(plan, "preview")
        checks = section_checks(own[:len(own) - len(plan.custom_commands)], run)
        if plan.vlans:
            out = outputs.get("show vlan", "")
            rows = {int(m.group(1)): (m.group(2), m.group(3))
                    for m in re.finditer(r"^(\d+)\s+(\S+)\s+(active|suspended)", out, re.M)}
            for v in plan.vlans:
                row = rows.get(v.id)
                checks.append(Check(f"VLAN {v.id} {v.name} active", row == (v.name, "active"),
                                    "missing" if row is None else f"name {row[0]}, {row[1]}"))
        for t in plan.trunks:
            out = outputs.get(f"show interfaces {t.interface} switchport", "")
            mode = first(r"^Operational Mode:\s*(.+)$", out)
            checks.append(Check(f"{t.interface} is a trunk", mode == "trunk", mode or "no mode line"))
        if plan.svis or plan.interfaces:
            rows = parse_ip_brief(outputs.get("show ip interface brief", ""), self.normalize_interface)
            for name, cidr in [(f"Vlan{s.vlan}", s.ip) for s in plan.svis] + \
                              [(r.interface, r.ip) for r in plan.interfaces]:
                row = rows.get(name)
                checks.append(Check(f"{name} address {cidr}", bool(row and row["ip"] == cidr),
                                    "not listed" if row is None else row["ip"]))
        if plan.routing and plan.routing.ospf:
            full = len(re.findall(r"\bFULL\b", outputs.get("show ip ospf neighbor", ""), re.I))
            checks.append(Check("OSPF neighbours FULL", full > 0, f"{full} FULL", required=False))
        if plan.routing and plan.routing.bgp:
            out = outputs.get("show ip bgp summary", "")
            for nb in plan.routing.bgp.neighbors:
                up = bool(re.search(rf"^\s*{re.escape(nb.ip)}\s.*\bEstab", out, re.M))
                checks.append(Check(f"BGP {nb.ip} established", up, required=False))
        return checks

    # -------------------------------------------------------- push support
    def denylist(self) -> list[tuple[tuple[str, ...], str]]:
        # Only the push engine opens, commits or aborts a configuration session.
        return [(("configure", "session"), "configure session"), (("commit",), "commit"),
                (("abort",), "abort"), (("rollback",), "rollback")]

    def error_patterns(self) -> list[str]:
        return list(ERROR_PATTERNS)

    def info_patterns(self) -> list[str]:
        return [r"^! "]  # EOS warnings start with "! "

    def save_command(self) -> str | None:
        return "copy running-config startup-config"

    def rollback_strategy(self) -> str:
        return "session_timer"

    def session(self, plan: ConfigPlan, name: str) -> Session:
        """docs/drivers/arista_eos.md section 1: a named configuration session, committed with a timer."""
        h, m = divmod(plan.revert_minutes, 60)
        return Session(strategy="session_timer", begin=f"configure session {name}",
                       arm=(f"commit timer {h:02d}:{m:02d}:00",), discard=("abort",),
                       confirm=(f"configure session {name} commit",), revert=(f"configure session {name} abort",),
                       applies_immediately=False)

    def management_interface(self, outputs: dict[str, str], mgmt_ip: str) -> str | None:
        rows = parse_ip_brief(outputs.get("show ip interface brief", ""), self.normalize_interface)
        return next((name for name, row in rows.items() if row["ip"].split("/")[0] == mgmt_ip), None)

    def backup_command(self) -> str:
        return "show running-config"

    def config_dump_commands(self) -> set[str]:
        return {"show running-config"}

    def management_commands(self) -> list[str]:
        return ["show ip interface brief"]

    def precheck_commands(self, plan: ConfigPlan) -> list[str]:
        return []

    def adapt_commands(self, plan, commands, outputs):
        return commands, []

    def prompts(self, command: str) -> list[tuple[str, str]] | None:
        return [] if command.startswith("commit") else None  # the commit can take a while: wait for the prompt

    def rollback_setup(self, running_config: str) -> list[str]:
        return []

    # ------------------------------------------------------------ discovery
    def facts_commands(self) -> list[str]:
        return ["show version", "show hostname"]

    def parse_facts(self, outputs: dict[str, str]) -> dict:
        v = outputs.get("show version", "")
        return {"model": first(r"^Arista (\S+)", v), "version": first(r"^Software image version:\s*(\S+)", v),
                "serial": first(r"^Serial number:\s*(\S+)", v),
                "hostname": first(r"^Hostname:\s*(\S+)", outputs.get("show hostname", ""))}

    def neighbor_commands(self) -> list[str]:
        return ["show lldp neighbors detail"]

    def parse_neighbors(self, outputs: dict[str, str]) -> list[dict]:
        out = []
        text = outputs.get("show lldp neighbors detail", "")
        for block in re.split(r"^(?=Interface \S+ detected)", text, flags=re.M):
            local = first(r"^Interface (\S+) detected", block)
            name = first(r'System Name:\s*"?([^"\s]+)', block)
            if local and name:
                port = first(r'Port ID\s*:\s*"?([^"\s]+)', block) or ""
                ip = first(r"Management Address\s*:\s*(\d+\.\d+\.\d+\.\d+)", block)
                out.append({"local": self.normalize_interface(local), "remote": name, "port": port, "ip": ip,
                            "protocol": "lldp"})
        return out


def parse_ip_brief(text: str, normalize) -> dict[str, dict]:
    """EOS 'show ip interface brief': Interface, IP Address (A.B.C.D/LEN), Status, Protocol, MTU [, Owner]."""
    rows = {}
    for m in re.finditer(r"^(\S+)\s+(\d+\.\d+\.\d+\.\d+/\d+|unassigned)\s+(.+?)\s+(up|down|lowerlayerdown|"
                         r"notpresent)\b", text, re.M):
        rows[normalize(m.group(1))] = {"ip": m.group(2), "status": m.group(3).strip(), "protocol": m.group(4)}
    return rows
