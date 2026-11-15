"""Huawei VRP driver (experimental; S5735-L and other S-series campus switches, V200 software that applies each
command at once). Commands and sources: docs/drivers/experimental.md section "Huawei VRP".

system-view → commands (sub-views end with "quit") → return; "save" asks "[Y/N]" and is answered "y".
VRP negates with "undo" (the safety checks treat it like "no").
"""

import re

from ...models.plan import ConfigPlan
from ..base import Check, Kind
from ..cisco_ios import parse_running_config
from ..common import first, normalize_by_types, section_checks
from .base import ExperimentalDriver

ERROR_PATTERNS = [r"^\s*Error:", r"Unrecognized command", r"Incomplete command", r"Wrong parameter",
                  r"Too many parameters", r"Ambiguous command"]
TYPES = ["GigabitEthernet", "XGigabitEthernet", "MultiGE", "Eth-Trunk", "Vlanif", "MEth", "LoopBack"]
IND = " "
DEFAULT_VTY_TIMEOUT = 10  # minutes; VRP does not show default values, so the default is not sent


def allow_pass(vlans: list[int]) -> list[str]:
    """'port trunk allow-pass vlan' takes at most 10 items ("10" or "30 to 35") per command."""
    ids, items, i = sorted(set(vlans)), [], 0
    while i < len(ids):
        j = i
        while j + 1 < len(ids) and ids[j + 1] == ids[j] + 1:
            j += 1
        items.append(f"{ids[i]} to {ids[j]}" if j > i else str(ids[i]))
        i = j + 1
    return [" ".join(items[k:k + 10]) for k in range(0, len(items), 10)]


class HuaweiVrp(ExperimentalDriver):
    os_id = "huawei_vrp"
    os_name = "Huawei VRP"
    netmiko_device_type = "huawei"
    config_prompt = r"\[[^\]\s]+\]"
    begin = "system-view"
    supports_vty_timeout = True
    supports_portfast = True
    supports_descriptions = True

    def normalize_interface(self, name: str) -> str:
        """'GE0/0/1'-style abbreviations are not guessed; 'Vlanif10' becomes the plan's logical 'Vlan10'."""
        name = normalize_by_types(name.strip(), TYPES)
        m = re.fullmatch(r"Vlanif(\d+)", name)
        return f"Vlan{m.group(1)}" if m else name

    def _review(self, plan: ConfigPlan, errors: dict[str, str], notes: list[str]) -> None:
        for i, t in enumerate(plan.trunks):
            if t.native_vlan != 1 and t.native_vlan not in t.allowed_vlans:
                errors[f"trunks.{i}.native_vlan"] = "on VRP the native VLAN (PVID) must also be an allowed VLAN"
        if plan.trunks:
            notes.append("A port that is an access port now must lose 'port default vlan' before it can become a "
                         "trunk; VRP refuses 'port link-type trunk' otherwise and the push stops there.")

    # ------------------------------------------------------------ generate
    def generate(self, plan: ConfigPlan, kind: Kind) -> list[str]:
        self._check_features(plan)
        out: list[str] = []
        if plan.basic:
            out.append(f"sysname {plan.basic.hostname}")
        if plan.ssh:
            s, u = plan.ssh, plan.ssh.username
            out += ["aaa", f"{IND}local-user {u} password irreversible-cipher {self._secret(plan, kind)}",
                    f"{IND}local-user {u} privilege level 15", f"{IND}local-user {u} service-type ssh", f"{IND}quit",
                    "stelnet server enable", f"ssh user {u}", f"ssh user {u} authentication-type password",
                    f"ssh user {u} service-type stelnet",
                    "user-interface vty 0 4", f"{IND}authentication-mode aaa", f"{IND}protocol inbound ssh"]
            if s.vty_timeout_minutes != DEFAULT_VTY_TIMEOUT:
                out.append(f"{IND}idle-timeout {s.vty_timeout_minutes} 0")
            out.append(f"{IND}quit")
        for v in plan.vlans:
            out += [f"vlan {v.id}", f"{IND}name {v.name}", f"{IND}quit"]
        for group in plan.access:
            for name in group.interfaces:
                out.append(f"interface {name}")
                if group.description:
                    out.append(f"{IND}description {group.description}")
                out += [f"{IND}port link-type access", f"{IND}port default vlan {group.vlan}"]
                if group.portfast:
                    out.append(f"{IND}stp edged-port enable")
                out.append(f"{IND}quit")
        for t in plan.trunks:
            out.append(f"interface {t.interface}")
            if t.description:
                out.append(f"{IND}description {t.description}")
            out.append(f"{IND}port link-type trunk")
            out += [f"{IND}port trunk allow-pass vlan {chunk}" for chunk in allow_pass(t.allowed_vlans)]
            if 1 not in t.allowed_vlans:  # a VRP trunk allows VLAN 1 by default
                out.append(f"{IND}undo port trunk allow-pass vlan 1")
            if t.native_vlan != 1:
                out.append(f"{IND}port trunk pvid vlan {t.native_vlan}")
            out.append(f"{IND}quit")
        out += list(plan.custom_commands)
        return out

    # -------------------------------------------------------------- verify
    def verify_commands(self, plan: ConfigPlan) -> list[str]:
        return ["display current-configuration"]

    def check(self, plan: ConfigPlan, outputs: dict[str, str]) -> list[Check]:
        text = outputs.get("display current-configuration")
        if text is None:
            return [Check("output of 'display current-configuration'", False, "command output missing")]
        # VRP separates sections with "#" lines; parse_running_config skips "!" lines, so turn them into those.
        run = parse_running_config(re.sub(r"^#\s*$", "!", text, flags=re.M))
        own = self.generate(plan, "preview")
        checks = section_checks(own[:len(own) - len(plan.custom_commands)], run)
        if plan.ssh:
            u = plan.ssh.username
            aaa = "\n".join(body for head, body in run["sections"] if head == "aaa")
            ok = bool(re.search(rf"^local-user {re.escape(u)} password irreversible-cipher \S", aaa, re.M))
            checks.append(Check(f"local user {u} password set", ok))
        return checks

    # -------------------------------------------------------- push support
    def denylist(self) -> list[tuple[tuple[str, ...], str]]:
        return [(("reboot",), "reboot"), (("reset", "saved-configuration"), "reset saved-configuration"),
                (("startup",), "startup"), (("undo", "local-user"), "undo local-user"), (("undo", "aaa"), "undo aaa"),
                (("undo", "user-interface"), "undo user-interface"), (("rsa", "local-key-pair", "destroy"),
                                                                       "rsa local-key-pair destroy"),
                (("stelnet", "server", "disable"), "stelnet server disable"), (("clear", "configuration"),
                                                                               "clear configuration")]

    def error_patterns(self) -> list[str]:
        return list(ERROR_PATTERNS)

    def save_command(self) -> str | None:
        return "save"

    def prompts(self, command: str) -> list[tuple[str, str]] | None:
        # "Warning: The current configuration will be written to the device. Are you sure to continue?[Y/N]:"
        return [(r"\[Y/N\]", "y")] if command == "save" else None

    def management_interface(self, outputs: dict[str, str], mgmt_ip: str) -> str | None:
        """'display ip interface brief': Interface  IP Address/Mask  Physical  Protocol."""
        for m in re.finditer(r"^(\S+)\s+(\d+\.\d+\.\d+\.\d+)/\d+\s+\S+\s+\S+", outputs.get(
                "display ip interface brief", ""), re.M):
            if m.group(2) == mgmt_ip:
                return self.normalize_interface(m.group(1))
        return None

    def backup_command(self) -> str:
        return "display current-configuration"

    def management_commands(self) -> list[str]:
        return ["display ip interface brief"]

    # ------------------------------------------------------------ discovery
    def facts_commands(self) -> list[str]:
        return ["display version", "display esn"]

    def parse_facts(self, outputs: dict[str, str]) -> dict:
        v = outputs.get("display version", "")
        return {"model": first(r"^HUAWEI (\S+).* uptime", v), "version": first(r"Version \S+ \(([^)]+)\)", v),
                "serial": first(r"ESN of (?:slot|device)[^:]*:\s*(\S+)", outputs.get("display esn", "")),
                "hostname": None}
