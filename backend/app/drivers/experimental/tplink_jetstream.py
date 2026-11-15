"""TP-Link JetStream (Omada) switch driver (experimental; TL-SG2000/3000, T1600G/T2600G CLI). Commands and
sources: docs/drivers/experimental.md section "TP-Link JetStream".

"configure" → commands → "end" (Netmiko leaves config mode one "exit" at a time, so "end" is sent first). A
port joins a VLAN with "switchport general allowed vlan N untagged|tagged" and gets its PVID with
"switchport pvid N"; "copy running-config startup-config" saves.
"""

import re

from ...models.plan import ConfigPlan
from ..base import Check, Kind, vlan_list
from ..cisco_ios import parse_running_config
from ..common import first, normalize_by_types, section_checks
from .base import ExperimentalDriver

ERROR_PATTERNS = [r"^\s*Error", r"^%\s", r"Bad command", r"Invalid", r"Incomplete command"]
TYPES = ["gigabitEthernet", "ten-gigabitEthernet", "port-channel", "vlan"]
IND = " "


class TplinkJetstream(ExperimentalDriver):
    os_id = "tplink_jetstream"
    os_name = "TP-Link JetStream"
    netmiko_device_type = "tplink_jetstream"
    begin = "configure"
    leave = ("end",)

    def normalize_interface(self, name: str) -> str:
        """'gi1/0/1', 'gigabitEthernet 1/0/1' → 'gigabitEthernet1/0/1' (the catalog's port names)."""
        name = normalize_by_types(name.strip(), TYPES)
        m = re.fullmatch(r"vlan(\d+)", name)
        return f"Vlan{m.group(1)}" if m else name

    @staticmethod
    def _if(name: str) -> str:
        """The CLI wants a space between the port type and its number: 'interface gigabitEthernet 1/0/1'."""
        m = re.fullmatch(r"([A-Za-z-]+)(\d.*)", name)
        return f"interface {m.group(1)} {m.group(2)}" if m else f"interface {name}"

    def _review(self, plan: ConfigPlan, errors: dict[str, str], notes: list[str]) -> None:
        if plan.basic and len(plan.basic.hostname) > 32:
            errors["basic.hostname"] = "TP-Link host names have at most 32 characters"

    # ------------------------------------------------------------ generate
    def generate(self, plan: ConfigPlan, kind: Kind) -> list[str]:
        self._check_features(plan)
        out: list[str] = []
        if plan.basic:
            out.append(f"hostname {plan.basic.hostname}")
        if plan.ssh:
            out += [f"user name {plan.ssh.username} privilege admin secret 0 {self._secret(plan, kind)}",
                    "ip ssh server", "ip ssh version v2"]
        for v in plan.vlans:
            out += [f"vlan {v.id}", f"{IND}name {v.name}", f"{IND}exit"]
        for group in plan.access:
            for name in group.interfaces:
                out += [self._if(name), f"{IND}switchport general allowed vlan {group.vlan} untagged",
                        f"{IND}switchport pvid {group.vlan}"]
                if group.vlan != 1:
                    out.append(f"{IND}no switchport general allowed vlan 1")
                out.append(f"{IND}exit")
        for t in plan.trunks:
            out.append(self._if(t.interface))
            tagged = [v for v in t.allowed_vlans if v != t.native_vlan]
            if tagged:
                out.append(f"{IND}switchport general allowed vlan {vlan_list(tagged)} tagged")
            if t.native_vlan in t.allowed_vlans:  # otherwise the trunk carries no untagged VLAN
                out += [f"{IND}switchport general allowed vlan {t.native_vlan} untagged",
                        f"{IND}switchport pvid {t.native_vlan}"]
            if 1 not in t.allowed_vlans:  # every port starts as an untagged member of VLAN 1
                out.append(f"{IND}no switchport general allowed vlan 1")
            out.append(f"{IND}exit")
        out += list(plan.custom_commands)
        return out

    # -------------------------------------------------------------- verify
    def verify_commands(self, plan: ConfigPlan) -> list[str]:
        return ["show running-config"]

    def check(self, plan: ConfigPlan, outputs: dict[str, str]) -> list[Check]:
        text = outputs.get("show running-config")
        if text is None:
            return [Check("output of 'show running-config'", False, "command output missing")]
        # The running config may quote names (hostname "sw1") and separates sections with "#" lines.
        text = re.sub(r'^(hostname|\s*name) "([^"]*)"\s*$', r"\1 \2", text, flags=re.M)
        run = parse_running_config(re.sub(r"^#\s*$", "!", text, flags=re.M))
        own = self.generate(plan, "preview")
        checks = section_checks(own[:len(own) - len(plan.custom_commands)], run)
        if plan.ssh:
            want = f"user name {plan.ssh.username} privilege admin secret 5 "
            checks.append(Check(f"local user {plan.ssh.username}", any(t.startswith(want) for t in run["top"])))
        return checks

    # -------------------------------------------------------- push support
    def denylist(self) -> list[tuple[tuple[str, ...], str]]:
        return [(("reboot",), "reboot"), (("reset",), "reset"), (("firmware",), "firmware"), (("boot",), "boot"),
                (("no", "user"), "no user"), (("no", "ip", "ssh"), "no ip ssh")]

    def error_patterns(self) -> list[str]:
        return list(ERROR_PATTERNS)

    def save_command(self) -> str | None:
        return "copy running-config startup-config"

    def management_interface(self, outputs: dict[str, str], mgmt_ip: str) -> str | None:
        """The interface whose 'ip address A M' in the running config is the management address."""
        for name, body in parse_running_config(outputs.get("show running-config", ""))["interfaces"].items():
            for line in body.splitlines():
                m = re.match(r"ip address\s+(\d+\.\d+\.\d+\.\d+)", line)
                if m and m.group(1) == mgmt_ip:
                    return self.normalize_interface(name.replace(" ", ""))
        return None

    def backup_command(self) -> str:
        return "show running-config"

    def management_commands(self) -> list[str]:
        return ["show running-config"]

    # ------------------------------------------------------------ discovery
    def facts_commands(self) -> list[str]:
        return ["show system-info"]

    def parse_facts(self, outputs: dict[str, str]) -> dict:
        s = outputs.get("show system-info", "")
        return {"model": first(r"Hardware Version\s*[-:]\s*(.+)$", s),
                "version": first(r"Software Version\s*[-:]\s*(.+)$", s),
                "serial": first(r"Serial Number\s*[-:]\s*(\S+)", s),
                "hostname": first(r"System Name\s*[-:]\s*(\S+)", s)}
