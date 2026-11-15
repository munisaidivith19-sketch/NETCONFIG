"""HPE Aruba Networking AOS-CX driver (CX 6100, 6300, AOS-CX Simulator). Commands and sources:
docs/drivers/aruba_aoscx.md. Lines marked [LAB] there are proven on the Simulator before the driver is "tested".

Safe change window: "checkpoint auto N" (exec mode) starts a switch-side timer; "checkpoint auto confirm" keeps
the change. There is no documented "roll back now" command, so a failed push is undone by the switch's own
timer: the job reports the time at which the old configuration comes back.

Status: experimental (docs/LAB_TESTING.md, section "Aruba AOS-CX Simulator").
"""

import ipaddress
import re

from ..models.plan import ConfigPlan
from ..security.masking import MASK
from .base import Check, Kind, ModelInfo, Session, UnsupportedFeature, vlan_list
from .cisco_ios import parse_running_config
from .common import dhcp_range, first, logical, normalize_by_types, section_checks, vlan_rows

CAPABILITIES = {"vlans", "access", "trunk", "svi", "routed_if", "dhcp", "static", "ospf", "bgp", "ssh",
                "default_gateway"}  # no NAT and no EIGRP on AOS-CX switches
ERROR_PATTERNS = [r"^\s*Invalid input", r"% Command incomplete", r"Ambiguous command", r"% Unknown command",
                  r"^\s*Error", r"^%\s"]
MAX_TIMER = 60  # checkpoint auto: 1-60 minutes
IND = "    "


class ArubaAoscx:
    os_id = "aruba_aoscx"
    os_name = "Aruba AOS-CX"
    netmiko_device_type = "aruba_aoscx"
    capabilities = CAPABILITIES
    cli_syntax = "ios"
    config_prompt = r"\(config[^)]*\)#"

    def __init__(self, model: ModelInfo):
        self.model = model
        self.flags = model.flags

    def normalize_interface(self, name: str) -> str:
        """Ports are typed as shown (1/1/1). 'vlan 10' / 'loopback 0' become the plan's Vlan10 / Loopback0."""
        name = name.strip()
        return normalize_by_types(name, ["Vlan", "Loopback"]) if name[:1].isalpha() else name

    @staticmethod
    def _if(name: str) -> str:
        kind = logical(name)
        return f"interface {kind[0]} {kind[1]}" if kind else f"interface {name}"

    # ------------------------------------------------------------- review
    def review(self, plan: ConfigPlan) -> tuple[dict[str, str], list[str]]:
        errors, notes = {}, []
        if plan.revert_minutes > MAX_TIMER:
            errors["revert_minutes"] = f"AOS-CX 'checkpoint auto' allows at most {MAX_TIMER} minutes"
        if plan.basic and len(plan.basic.hostname) > 32:
            errors["basic.hostname"] = "AOS-CX host names have at most 32 characters"
        h = plan.hardening
        if h and h.login_block:
            errors["hardening.login_block"] = "AOS-CX has no 'login block-for'; turn this option off"
        if h and h.banner:
            errors["hardening.banner"] = ("an AOS-CX banner is typed interactively, which this driver does not "
                                          "drive yet; turn the banner off")
        if h and h.password_encryption:
            notes.append("AOS-CX always stores passwords encrypted, so 'password encryption' needs no command.")
        if plan.ssh:
            u = plan.ssh.username
            if u != u.lower() or u in ("admin", "root"):
                errors["ssh.username"] = "AOS-CX user names are lower case and cannot be 'admin' or 'root'"
            if plan.ssh.set_enable_secret:
                errors["ssh.set_enable_secret"] = "AOS-CX has no enable secret: the user group gives the rights"  # noqa: S105  # nosec B105 - a message
            if plan.ssh.regenerate_keys:
                errors["ssh.regenerate_keys"] = "AOS-CX creates its SSH host keys itself"
        for i, group in enumerate(plan.access):
            if group.port_security:
                errors[f"access.{i}.port_security"] = "port security is not supported by the AOS-CX driver yet"
        for i, t in enumerate(plan.trunks):
            if t.native_vlan not in t.allowed_vlans:
                errors[f"trunks.{i}.native_vlan"] = "on AOS-CX the native VLAN must also be an allowed VLAN"
        for i, pool in enumerate(plan.dhcp):
            if not dhcp_range(pool)[2]:
                notes.append(f"DHCP pool {pool.name}: AOS-CX gets one address range here, so only the largest "
                             f"free block is used ({' – '.join(dhcp_range(pool)[:2])}).")
            if len(pool.dns_servers) > 4:
                errors[f"dhcp.{i}.dns_servers"] = "AOS-CX takes at most four DNS servers per pool"
        if plan.routing and plan.routing.ospf:
            in_ospf = {oi.interface for oi in plan.routing.ospf.interfaces}
            for i, p in enumerate(plan.routing.ospf.passive_interfaces):
                if p not in in_ospf:
                    errors[f"routing.ospf.passive_interfaces.{i}"] = ("on AOS-CX a passive interface must also be "
                                                                       "in the OSPF interface list")
        notes.append(f"If the push fails, the switch restores its old configuration by itself when the "
                     f"{plan.revert_minutes}-minute checkpoint timer ends (AOS-CX has no 'roll back now').")
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
                out.append(f"ip dns domain-name {plan.basic.domain}")
        if plan.hardening and plan.hardening.disable_http:
            out.append("no https-server vrf default")
        if plan.ssh:
            s = plan.ssh
            if kind == "preview":
                pw = MASK
            elif s.password is None:
                raise ValueError("ssh.password is required to push this plan")
            else:
                pw = s.password.get_secret_value()
            out += [f"user {s.username} group administrators password plaintext {pw}", "ssh server vrf default",
                    "cli-session", f"{IND}timeout {s.vty_timeout_minutes}"]
        for v in plan.vlans:
            out += [f"vlan {v.id}", f"{IND}name {v.name}"]
        for group in plan.access:
            for name in group.interfaces:
                out.append(f"interface {name}")
                if group.description:
                    out.append(f"{IND}description {group.description}")
                out += [f"{IND}no shutdown", f"{IND}no routing", f"{IND}vlan access {group.vlan}"]
                if group.portfast:
                    out.append(f"{IND}spanning-tree port-type admin-edge")
        for t in plan.trunks:
            out.append(f"interface {t.interface}")
            if t.description:
                out.append(f"{IND}description {t.description}")
            # "vlan trunk native" resets the allowed list to "all", so the allowed list must come after it.
            out += [f"{IND}no shutdown", f"{IND}no routing", f"{IND}vlan trunk native {t.native_vlan}",
                    f"{IND}vlan trunk allowed {vlan_list(t.allowed_vlans)}"]
        for s in plan.svis:
            out.append(f"interface vlan {s.vlan}")
            if s.description:
                out.append(f"{IND}description {s.description}")
            out += [f"{IND}ip address {s.ip}", f"{IND}no shutdown"]
        for r in plan.interfaces:
            out.append(self._if(r.interface))
            if r.description:
                out.append(f"{IND}description {r.description}")
            if logical(r.interface) is None:
                out += [f"{IND}no shutdown", f"{IND}routing"]
            out.append(f"{IND}ip address {r.ip}")
        self._dhcp(plan, out)
        for st in plan.statics:
            hop = st.next_hop or st.interface
            line = f"ip route {ipaddress.IPv4Network(st.prefix)} {hop}"
            out.append(f"{line} distance {st.distance}" if st.distance else line)
        if plan.default_gateway:
            out.append(f"ip route 0.0.0.0/0 {plan.default_gateway}")
        self._routing(plan, out)
        out += list(plan.custom_commands)
        return out

    def _dhcp(self, plan: ConfigPlan, out: list[str]) -> None:
        if not plan.dhcp:
            return
        out.append("dhcp-server vrf default")
        for pool in plan.dhcp:
            low, high, _ = dhcp_range(pool)
            prefix = ipaddress.IPv4Network(pool.network).prefixlen
            out += [f"{IND}pool {pool.name}", f"{IND * 2}range {low} {high} prefix-len {prefix}",
                    f"{IND * 2}default-router {pool.default_router}"]
            if pool.dns_servers:
                out.append(f"{IND * 2}dns-server " + " ".join(pool.dns_servers))
            if pool.domain:
                out.append(f"{IND * 2}domain-name {pool.domain}")
            if pool.lease_days != 1:  # the default lease is one day
                out.append(f"{IND * 2}lease {pool.lease_days:02d}:00:00")
            out.append(f"{IND * 2}exit")
        out.append(f"{IND}enable")

    def _routing(self, plan: ConfigPlan, out: list[str]) -> None:
        r = plan.routing
        if not r:
            return
        if r.ospf:
            o = r.ospf
            areas = sorted({oi.area for oi in o.interfaces})
            out += [f"router ospf {o.process_id}", f"{IND}router-id {o.router_id}"]
            out += [f"{IND}area {ipaddress.IPv4Address(a)}" for a in areas]
            passive = set(o.passive_interfaces)
            for oi in o.interfaces:
                out += [self._if(oi.interface), f"{IND}ip ospf {o.process_id} area {ipaddress.IPv4Address(oi.area)}"]
                if oi.interface in passive:
                    out.append(f"{IND}ip ospf passive")
        if r.bgp:
            b = r.bgp
            out += [f"router bgp {b.asn}", f"{IND}bgp router-id {b.router_id}"]
            for nb in b.neighbors:
                out.append(f"{IND}neighbor {nb.ip} remote-as {nb.remote_as}")
                if nb.description:
                    out.append(f"{IND}neighbor {nb.ip} description {nb.description}")
            out.append(f"{IND}address-family ipv4 unicast")
            out += [f"{IND * 2}neighbor {nb.ip} activate" for nb in b.neighbors]
            out += [f"{IND * 2}network {ipaddress.IPv4Network(n)}" for n in b.networks]
            out.append(f"{IND}exit-address-family")

    # -------------------------------------------------------------- verify
    def verify_commands(self, plan: ConfigPlan) -> list[str]:
        cmds = ["show running-config"]
        if plan.vlans:
            cmds.append("show vlan")
        if plan.routing and plan.routing.ospf:
            cmds.append("show ip ospf neighbors")
        if plan.routing and plan.routing.bgp:
            cmds.append("show bgp ipv4 unicast summary")
        return cmds

    def check(self, plan: ConfigPlan, outputs: dict[str, str]) -> list[Check]:
        if "show running-config" not in outputs:
            return [Check("output of 'show running-config'", False, "command output missing")]
        run = parse_running_config(outputs["show running-config"])
        own = self.generate(plan, "preview")
        checks = section_checks(own[:len(own) - len(plan.custom_commands)], run)
        if plan.ssh:
            want = f"user {plan.ssh.username} group administrators password ciphertext "
            checks.append(Check(f"local user {plan.ssh.username}", any(t.startswith(want) for t in run["top"])))
        if plan.vlans:
            rows = {int(m.group(1)): m.group(2)
                    for m in re.finditer(r"^(\d+)\s+(\S+)\s+(?:up|down)\b", outputs.get("show vlan", ""), re.M)}
            for v in plan.vlans:
                checks.append(Check(f"VLAN {v.id} {v.name}", rows.get(v.id) == v.name, rows.get(v.id, "missing")))
        if plan.routing and plan.routing.ospf:
            full = len(re.findall(r"\bFULL\b", outputs.get("show ip ospf neighbors", "")))
            checks.append(Check("OSPF neighbours FULL", full > 0, f"{full} FULL", required=False))
        if plan.routing and plan.routing.bgp:
            out = outputs.get("show bgp ipv4 unicast summary", "")
            for nb in plan.routing.bgp.neighbors:
                up = bool(re.search(rf"^\s*{re.escape(nb.ip)}\s.*\bEstablished\b", out, re.M))
                checks.append(Check(f"BGP {nb.ip} established", up, required=False))
        return checks

    # -------------------------------------------------------- push support
    def denylist(self) -> list[tuple[tuple[str, ...], str]]:
        # Only the push engine starts or confirms a checkpoint; checkpoints and users are never removed.
        return [(("checkpoint",), "checkpoint"), (("erase",), "erase"), (("boot",), "boot"),
                (("no", "user"), "no user"), (("zeroize",), "zeroize")]

    def error_patterns(self) -> list[str]:
        return list(ERROR_PATTERNS)

    def info_patterns(self) -> list[str]:
        return [r"WARNING Please \"checkpoint auto confirm\""]

    def save_command(self) -> str | None:
        return "write memory"

    def rollback_strategy(self) -> str:
        return "checkpoint"

    def session(self, plan: ConfigPlan, name: str) -> Session:
        """docs/drivers/aruba_aoscx.md section 1. "end" first: Netmiko only recognises "(config)#", not the
        sub-contexts such as "(config-if)#", so the engine must leave them itself."""
        return Session(strategy="checkpoint", start=(f"checkpoint auto {plan.revert_minutes}",),
                       begin="configure terminal", leave=("end",), confirm=("checkpoint auto confirm",))

    def management_interface(self, outputs: dict[str, str], mgmt_ip: str) -> str | None:
        """'show ip interface brief' is not in the 10.10 guides, so the address is found in the running config:
        'ip address A/LEN' (in-band) or 'ip static A/LEN' (the out-of-band mgmt port)."""
        for name, body in parse_running_config(outputs.get("show running-config", ""))["interfaces"].items():
            for line in body.splitlines():
                m = re.match(r"(?:ip address|ip static)\s+(\d+\.\d+\.\d+\.\d+)/\d+", line)
                if m and m.group(1) == mgmt_ip:
                    return self.normalize_interface(name)
        return None

    def backup_command(self) -> str:
        return "show running-config"

    def config_dump_commands(self) -> set[str]:
        return {"show running-config"}

    def management_commands(self) -> list[str]:
        return ["show running-config"]

    def precheck_commands(self, plan: ConfigPlan) -> list[str]:
        return []

    def adapt_commands(self, plan, commands, outputs):
        return commands, []

    def prompts(self, command: str) -> list[tuple[str, str]] | None:
        return None

    def rollback_setup(self, running_config: str) -> list[str]:
        return []

    # ------------------------------------------------------------ discovery
    def facts_commands(self) -> list[str]:
        return ["show system"]

    def parse_facts(self, outputs: dict[str, str]) -> dict:
        s = outputs.get("show system", "")
        return {"model": first(r"^Product Name\s*:\s*(.+)$", s), "version": first(r"^AOS-CX Version\s*:\s*(\S+)", s),
                "serial": first(r"^Chassis Serial Nbr\s*:\s*(\S+)", s), "hostname": first(r"^Hostname\s*:\s*(\S+)", s)}

    def vlan_commands(self) -> list[str]:
        return ["show vlan"]

    def parse_vlans(self, outputs: dict[str, str]) -> list[dict]:
        return vlan_rows(outputs.get("show vlan", ""), r"^(?P<id>\d+)\s+(?P<name>\S+)\s+(?:up|down)\b")

    def neighbor_commands(self) -> list[str]:
        return ["show lldp neighbor-info detail"]

    def parse_neighbors(self, outputs: dict[str, str]) -> list[dict]:
        out = []
        text = outputs.get("show lldp neighbor-info detail", "")
        for block in re.split(r"^(?=Port\s*:)", text, flags=re.M):
            local = first(r"^Port\s*:\s*(\S+)", block)
            name = first(r"^Neighbor Chassis-Name\s*:\s*(\S+)", block)
            if local and name:
                port = first(r"^Neighbor Port-ID\s*:\s*(\S+)", block) or ""
                out.append({"local": local, "remote": name, "port": port,
                            "ip": first(r"^Neighbor Management-Address\s*:\s*(\d+\.\d+\.\d+\.\d+)", block),
                            "protocol": "lldp"})
        return out
