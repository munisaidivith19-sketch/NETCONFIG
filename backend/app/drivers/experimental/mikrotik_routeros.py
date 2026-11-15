"""MikroTik RouterOS v7 driver (experimental; CRS3xx switches and CHR). Commands and sources:
docs/drivers/experimental.md section "MikroTik RouterOS".

VLANs use bridge VLAN filtering on one bridge (driver flag "bridge", default "bridge" as in the default
configuration): access ports get a PVID and accept only untagged frames, trunk ports carry tagged VLANs from the
bridge VLAN table, and VLAN filtering is switched on last, as the MikroTik guide says. RouterOS applies each
command at once and keeps it (there is no "save").
"""

import re

from ...models.plan import ConfigPlan
from ..base import Check, Kind
from ..common import first
from .base import ExperimentalDriver

ERROR_PATTERNS = [r"^\s*failure:", r"bad command name", r"expected end of command", r"syntax error",
                  r"input does not match any value", r"no such item", r"invalid value", r"ambiguous value",
                  r"^\s*error:"]
ACCESS = "frame-types=admit-only-untagged-and-priority-tagged"


def _ids(text: str) -> set[int]:
    out: set[int] = set()
    for part in text.split(","):
        a, _, b = part.partition("-")
        if a.isdigit() and (not b or b.isdigit()):
            out.update(range(int(a), int(b or a) + 1))
    return out


def _attr(name: str, line: str) -> str | None:
    """The value of name=... in a 'print terse' line (not current-name= or untagged= for name=tagged)."""
    return first(rf"(?<![\w-]){re.escape(name)}=(\S*)", line)


class MikrotikRouteros(ExperimentalDriver):
    os_id = "mikrotik_routeros"
    os_name = "MikroTik RouterOS"
    netmiko_device_type = "mikrotik_routeros"
    cli_syntax = "routeros"
    config_prompt = r"\] >"
    max_vlan_name = 32  # stored as the VLAN entry's comment

    @property
    def bridge(self) -> str:
        return self.flags.get("bridge", "bridge")

    def _review(self, plan: ConfigPlan, errors: dict[str, str], notes: list[str]) -> None:
        planned = {v.id for v in plan.vlans}
        for i, t in enumerate(plan.trunks):
            missing = sorted(set(t.allowed_vlans) - planned - {t.native_vlan})
            if missing:
                errors[f"trunks.{i}.allowed_vlans"] = ("on RouterOS the tagged VLANs of a trunk are entries in the "
                                                       f"bridge VLAN table: add VLAN(s) {missing} to the VLAN list")
        if plan.vlans or plan.access or plan.trunks:
            notes.append(f"VLAN filtering is switched on for bridge '{self.bridge}' as the last step. Ports that are "
                         "not in this plan keep PVID 1; check that your own connection still reaches the device.")
        if plan.ssh:
            notes.append(f"RouterOS: '/user add' fails if the user '{plan.ssh.username}' already exists; the push "
                         "then stops at that command.")
        if plan.save:
            notes.append("RouterOS keeps every change at once; there is no separate save step.")

    # ------------------------------------------------------------ generate
    def generate(self, plan: ConfigPlan, kind: Kind) -> list[str]:
        self._check_features(plan)
        out: list[str] = []
        if plan.basic:
            out.append(f"/system identity set name={plan.basic.hostname}")
        if plan.ssh:
            s = plan.ssh
            out += [f"/user add name={s.username} group=full password={self._secret(plan, kind)}",
                    "/ip service set ssh disabled=no", "/ip ssh set strong-crypto=yes"]
        b = self.bridge
        for v in plan.vlans:
            tagged = [t.interface for t in plan.trunks if v.id in t.allowed_vlans and v.id != t.native_vlan]
            line = f"/interface bridge vlan add bridge={b} vlan-ids={v.id} comment={v.name}"
            out.append(f"{line} tagged={','.join(tagged)}" if tagged else line)
        for group in plan.access:
            for name in group.interfaces:
                out.append(f"/interface bridge port set [find interface={name}] pvid={group.vlan} {ACCESS} "
                           "ingress-filtering=yes")
        for t in plan.trunks:
            port = f"/interface bridge port set [find interface={t.interface}]"
            if t.native_vlan in t.allowed_vlans:
                # The native VLAN is the port's PVID; RouterOS adds the port to it as an untagged member by itself.
                out.append(f"{port} pvid={t.native_vlan} frame-types=admit-all ingress-filtering=yes")
            else:  # no untagged VLAN on this trunk
                out.append(f"{port} frame-types=admit-only-vlan-tagged ingress-filtering=yes")
        if plan.vlans or plan.access or plan.trunks:
            out.append(f"/interface bridge set [find name={b}] vlan-filtering=yes")
        out += list(plan.custom_commands)
        return out

    # -------------------------------------------------------------- verify
    def verify_commands(self, plan: ConfigPlan) -> list[str]:
        cmds = []
        if plan.basic:
            cmds.append("/system identity print")
        if plan.ssh:
            cmds.append("/user print terse")
        if plan.vlans or plan.access or plan.trunks:
            cmds += ["/interface bridge print terse", "/interface bridge vlan print terse",
                     "/interface bridge port print terse"]
        return cmds

    def check(self, plan: ConfigPlan, outputs: dict[str, str]) -> list[Check]:
        checks = []
        if plan.basic:
            name = first(r"name:\s*(\S+)", outputs.get("/system identity print", ""))
            checks.append(Check(f"identity {plan.basic.hostname}", name == plan.basic.hostname, name or "missing"))
        if plan.ssh:
            rows = outputs.get("/user print terse", "").splitlines()
            ok = any(_attr("name", r) == plan.ssh.username and _attr("group", r) == "full" for r in rows)
            checks.append(Check(f"local user {plan.ssh.username} (group full)", ok))
        if plan.vlans or plan.access or plan.trunks:
            bridges = outputs.get("/interface bridge print terse", "").splitlines()
            on = any(_attr("name", r) == self.bridge and _attr("vlan-filtering", r) == "yes" for r in bridges)
            checks.append(Check(f"VLAN filtering on bridge {self.bridge}", on))
        vlan_rows = outputs.get("/interface bridge vlan print terse", "").splitlines()
        for v in plan.vlans:
            row = next((r for r in vlan_rows if v.id in _ids(_attr("vlan-ids", r) or "")
                        and _attr("bridge", r) == self.bridge), None)
            want = {t.interface for t in plan.trunks if v.id in t.allowed_vlans and v.id != t.native_vlan}
            have = set((_attr("tagged", row) or "").split(",")) if row else set()
            checks.append(Check(f"VLAN {v.id} {v.name}", row is not None and want <= have,
                                "missing" if row is None else f"tagged: {','.join(sorted(have - {''})) or 'none'}"))
        port_rows = outputs.get("/interface bridge port print terse", "").splitlines()
        wanted = [(n, g.vlan) for g in plan.access for n in g.interfaces] + \
                 [(t.interface, t.native_vlan) for t in plan.trunks if t.native_vlan in t.allowed_vlans]
        for name, pvid in wanted:
            row = next((r for r in port_rows if _attr("interface", r) == name), None)
            got = _attr("pvid", row) if row else None
            checks.append(Check(f"{name} PVID {pvid}", got == str(pvid), got or "not a bridge port"))
        return checks

    # -------------------------------------------------------- push support
    def denylist(self) -> list[tuple[tuple[str, ...], str]]:
        # Paths are split into words first ("/system/reboot" = "system reboot"). "remove"/"unset" anywhere are
        # blocked by the management rules (services/safety.py).
        return [(("system", "reboot"), "system reboot"), (("system", "shutdown"), "system shutdown"),
                (("system", "reset-configuration"), "system reset-configuration"),
                (("system", "package"), "system package"), (("system", "routerboard"), "system routerboard"),
                (("system", "backup", "load"), "system backup load"), (("import",), "import"),
                (("system", "script"), "system script"), (("system", "scheduler"), "system scheduler"),
                (("tool", "fetch"), "tool fetch"), (("file",), "file"), (("user", "set"), "user set"),
                (("user", "disable"), "user disable")]

    def error_patterns(self) -> list[str]:
        return list(ERROR_PATTERNS)

    def save_command(self) -> str | None:
        return None

    def management_interface(self, outputs: dict[str, str], mgmt_ip: str) -> str | None:
        for row in outputs.get("/ip address print terse", "").splitlines():
            addr = _attr("address", row)
            if addr and addr.split("/")[0] == mgmt_ip:
                return _attr("interface", row)
        return None

    def backup_command(self) -> str:
        return "/export terse"

    def management_commands(self) -> list[str]:
        return ["/ip address print terse"]

    # ------------------------------------------------------------ discovery
    def facts_commands(self) -> list[str]:
        return ["/system resource print", "/system routerboard print", "/system identity print"]

    def parse_facts(self, outputs: dict[str, str]) -> dict:
        res, rb = outputs.get("/system resource print", ""), outputs.get("/system routerboard print", "")
        return {"model": first(r"^\s*model:\s*(.+)$", rb) or first(r"^\s*board-name:\s*(.+)$", res),
                "version": first(r"^\s*version:\s*(\S+)", res),
                "serial": first(r"^\s*serial-number:\s*(\S+)", rb),
                "hostname": first(r"^\s*name:\s*(\S+)", outputs.get("/system identity print", ""))}
