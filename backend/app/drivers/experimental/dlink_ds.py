"""D-Link DGS-1210 / DES "xStack"-style CLI driver (experimental). Commands and sources:
docs/drivers/experimental.md section "D-Link DGS-1210" (DGS-1210 Series CLI Reference Guide).

The CLI has no configuration mode: every command runs at the main prompt and applies at once; "save" writes it
to NV-RAM. Ports are plain numbers ("1"-"28") and port lists use ranges ("1-3,5").
"""

import re

from ...models.plan import ConfigPlan
from ..base import Check, Kind, vlan_list
from ..common import first
from .base import ExperimentalDriver

ERROR_PATTERNS = [r"\bFail", r"Next possible completions", r"Available commands", r"^\s*ERROR", r"Invalid",
                  r"does not exist", r"already exist"]
MAX_PASSWORD = 15  # "create account": passwords are 0-15 characters
MAX_USERNAME = 15


def ports(names: list[str]) -> str:
    return vlan_list([int(n) for n in names])


def _port_set(text: str) -> set[str]:
    out: set[str] = set()
    for part in text.replace(" ", "").split(","):
        a, _, b = part.partition("-")
        if a.isdigit() and (not b or b.isdigit()):
            out.update(str(i) for i in range(int(a), int(b or a) + 1))
    return out


def parse_show_vlan(text: str) -> dict[int, dict]:
    """'show vlan' blocks: VID : 1   VLAN NAME : default / Member Ports : ... / Untagged Ports : ..."""
    out: dict[int, dict] = {}
    for block in re.split(r"(?=^\s*VID\s*:)", text, flags=re.M):
        vid = first(r"^\s*VID\s*:\s*(\d+)", block)
        if not vid:
            continue
        member = _port_set(first(r"^\s*Member Ports\s*:[ \t]*(.*)$", block) or "")
        untagged = _port_set(first(r"^\s*Untagged Ports\s*:[ \t]*(.*)$", block) or "")
        tagged = _port_set(first(r"^\s*Tagged Ports\s*:[ \t]*(.*)$", block) or "")
        out[int(vid)] = {"name": first(r"VLAN NAME\s*:\s*(\S+)", block), "member": member | untagged | tagged,
                         "untagged": untagged, "tagged": tagged | (member - untagged)}
    return out


class DlinkDs(ExperimentalDriver):
    os_id = "dlink_ds"
    os_name = "D-Link DGS"
    netmiko_device_type = "dlink_ds"
    cli_syntax = "dlink"
    config_prompt = r"#"
    max_vlan_name = 20  # "create vlan <vlan_name 20>" in the DGS-1210 guide
    supports_password_encryption = True

    def _review(self, plan: ConfigPlan, errors: dict[str, str], notes: list[str]) -> None:
        if plan.basic and len(plan.basic.hostname) > 32:
            errors["basic.hostname"] = "D-Link system names have at most 32 characters"
        if plan.ssh:
            if len(plan.ssh.username) > MAX_USERNAME:
                errors["ssh.username"] = f"D-Link user names have at most {MAX_USERNAME} characters"
            if plan.ssh.password and len(plan.ssh.password.get_secret_value()) > MAX_PASSWORD:
                errors["ssh.password"] = f"D-Link passwords have at most {MAX_PASSWORD} characters"
            notes.append(f"D-Link: the account '{plan.ssh.username}' must already exist (creating one asks for the "
                         "password interactively); this plan sets its password and turns SSH on.")
        for i, t in enumerate(plan.trunks):
            if 1 not in t.allowed_vlans:
                errors[f"trunks.{i}.allowed_vlans"] = ("the D-Link driver does not remove ports from VLAN 1 yet: add "
                                                       "VLAN 1 to the allowed list")
            elif t.native_vlan not in t.allowed_vlans:
                errors[f"trunks.{i}.native_vlan"] = "on D-Link the native VLAN (PVID) must also be an allowed VLAN"
        if any(g.vlan != 1 for g in plan.access):
            notes.append("D-Link: the verification checks that access ports left VLAN 1; if the switch keeps them "
                         "there, the push is reported as failed (lab checklist item).")

    # ------------------------------------------------------------ generate
    def generate(self, plan: ConfigPlan, kind: Kind) -> list[str]:
        self._check_features(plan)
        out: list[str] = []
        if plan.basic:
            out.append(f"config snmp system_name {plan.basic.hostname}")
        if plan.hardening and plan.hardening.password_encryption:
            out.append("enable password encryption")
        if plan.ssh:
            out += [f"config account {plan.ssh.username} encrypt plain_text {self._secret(plan, kind)}", "enable ssh"]
        for v in plan.vlans:
            out.append(f"create vlan {v.name} tag {v.id}")
        by_vlan: dict[int, list[str]] = {}
        for group in plan.access:
            by_vlan.setdefault(group.vlan, []).extend(group.interfaces)
        for vid, names in by_vlan.items():
            out += [f"config vlan vlanid {vid} add untagged {ports(names)}",
                    f"config port_vlan {ports(names)} pvid {vid}"]
        tagged: dict[int, list[str]] = {}
        for t in plan.trunks:
            for vid in t.allowed_vlans:
                if vid != t.native_vlan:
                    tagged.setdefault(vid, []).append(t.interface)
        for vid in sorted(tagged):
            out.append(f"config vlan vlanid {vid} add tagged {ports(tagged[vid])}")
        for t in plan.trunks:  # review(): the native VLAN is always an allowed VLAN here
            out += [f"config vlan vlanid {t.native_vlan} add untagged {t.interface}",
                    f"config port_vlan {t.interface} pvid {t.native_vlan}"]
        out += list(plan.custom_commands)
        return out

    def precheck_commands(self, plan: ConfigPlan) -> list[str]:
        return ["show vlan"] if plan.vlans else []

    def adapt_commands(self, plan, commands, outputs):
        """'create vlan' fails for a VLAN that exists: rename an existing one instead ('config vlan vlanid N name')."""
        existing = parse_show_vlan(outputs.get("show vlan", ""))
        out, notes = [], []
        for cmd in commands:
            m = re.fullmatch(r"create vlan (\S+) tag (\d+)", cmd)
            if m and int(m.group(2)) in existing:
                notes.append(f"VLAN {m.group(2)} already exists; it is renamed instead of created.")
                cmd = f"config vlan vlanid {m.group(2)} name {m.group(1)}"
            out.append(cmd)
        return out, notes

    # -------------------------------------------------------------- verify
    def verify_commands(self, plan: ConfigPlan) -> list[str]:
        cmds = []
        if plan.basic:
            cmds.append("show switch")
        if plan.vlans or plan.access or plan.trunks:
            cmds += ["show vlan", "show port_vlan pvid"]
        return cmds

    def check(self, plan: ConfigPlan, outputs: dict[str, str]) -> list[Check]:
        checks = []
        if plan.basic:
            name = first(r"System Name\s*:\s*(\S+)", outputs.get("show switch", ""))
            checks.append(Check(f"system name {plan.basic.hostname}", name == plan.basic.hostname, name or "missing"))
        vlans = parse_show_vlan(outputs.get("show vlan", ""))
        for v in plan.vlans:
            got = vlans.get(v.id, {}).get("name")
            checks.append(Check(f"VLAN {v.id} {v.name}", got == v.name, got or "missing"))
        pvids = dict(re.findall(r"^\s*(\d+)\s+(\d+)\s*$", outputs.get("show port_vlan pvid", ""), re.M))
        for group in plan.access:
            for p in group.interfaces:
                ok = p in vlans.get(group.vlan, {}).get("untagged", set()) and pvids.get(p) == str(group.vlan)
                checks.append(Check(f"port {p} untagged in VLAN {group.vlan}, PVID {group.vlan}", ok,
                                    f"PVID {pvids.get(p, '?')}"))
                if group.vlan != 1:  # still in VLAN 1 would leak that VLAN onto the access port
                    left = p not in vlans.get(1, {}).get("member", set())
                    checks.append(Check(f"port {p} left VLAN 1", left, "" if left else "still a VLAN 1 member"))
        for t in plan.trunks:
            missing = [vid for vid in t.allowed_vlans if vid != t.native_vlan
                       and t.interface not in vlans.get(vid, {}).get("tagged", set())]
            checks.append(Check(f"port {t.interface} tagged in VLANs {vlan_list(t.allowed_vlans)}", not missing,
                                f"not tagged in {vlan_list(missing)}" if missing else ""))
            pvid_ok = pvids.get(t.interface) == str(t.native_vlan)
            checks.append(Check(f"port {t.interface} PVID {t.native_vlan}", pvid_ok,
                                f"PVID {pvids.get(t.interface, '?')}"))
        return checks

    # -------------------------------------------------------- push support
    def denylist(self) -> list[tuple[tuple[str, ...], str]]:
        return [(("reboot",), "reboot"), (("reset",), "reset"), (("download",), "download"),
                (("upload",), "upload"), (("config", "firmware"), "config firmware"),
                # "create account" asks for the password interactively, which would hang the push
                (("create", "account"), "create account")]

    def error_patterns(self) -> list[str]:
        return list(ERROR_PATTERNS)

    def save_command(self) -> str | None:
        return "save"

    def management_interface(self, outputs: dict[str, str], mgmt_ip: str) -> str | None:
        """'show ipif': the System interface's 'IP Address' and 'VLAN Name'; 'show vlan' maps the name to its ID."""
        text = outputs.get("show ipif", "")
        if first(r"IP Address\s*:\s*(\d+\.\d+\.\d+\.\d+)", text) != mgmt_ip:
            return None
        name = first(r"VLAN Name\s*:\s*(\S+)", text)
        vid = next((vid for vid, v in parse_show_vlan(outputs.get("show vlan", "")).items() if v["name"] == name),
                   None)
        return f"Vlan{vid}" if vid is not None else None

    def backup_command(self) -> str:
        return "show config current_config"

    def management_commands(self) -> list[str]:
        return ["show ipif", "show vlan"]

    # ------------------------------------------------------------ discovery
    def facts_commands(self) -> list[str]:
        return ["show switch"]

    def parse_facts(self, outputs: dict[str, str]) -> dict:
        s = outputs.get("show switch", "")
        return {"model": first(r"Device Type\s*:\s*(.+)$", s), "version": first(r"Firmware Version\s*:\s*(.+)$", s),
                "serial": first(r"Serial Number\s*:\s*(\S+)", s), "hostname": first(r"System Name\s*:\s*(\S+)", s)}
