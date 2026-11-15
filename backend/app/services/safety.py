"""Push safety checks on the final command list (CLAUDE.md 8.5). They run on generated commands and on the
custom-commands box alike, so they never trust that validation ran first.

Matching rules (agreed in docs/TEST_PLAN.md 3.3):
- a line is split into separate commands at newlines, ``;``, ``|`` and ``&``;
- each command is trimmed, lower-cased, runs of whitespace are collapsed, and a leading ``do`` is removed;
- a word matches a keyword when it is a prefix of it (IOS abbreviations: ``rel`` = ``reload``);
- matching is on whole commands from the first word, so ``description reload-test`` is allowed.
Ambiguous short words (``de`` = debug/delete/description) are blocked whenever a denied command fits.
"""

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

# (keywords, label). A command is denied when its first words abbreviate all keywords in order.
DENYLIST: list[tuple[tuple[str, ...], str]] = [
    (("reload",), "reload"),
    (("erase",), "erase"),
    (("write", "erase"), "write erase"),
    (("delete",), "delete"),
    (("format",), "format"),
    (("no", "username"), "no username"),
    (("crypto", "key", "zeroize"), "crypto key zeroize"),
    (("request", "system", "zeroize"), "request system zeroize"),
    (("request", "system", "reboot"), "request system reboot"),
    (("debug", "all"), "debug all"),
    (("configure", "replace"), "configure replace"),
]
_SPLIT = re.compile(r"[\r\n;|&]+")


@dataclass(frozen=True)
class Violation:
    index: int  # position in the command list
    command: str
    rule: str

    @property
    def message(self) -> str:
        return f"'{self.command.strip()}' is blocked: {self.rule}"


def words_of(command: str) -> list[str]:
    words = command.strip().lower().split()
    if words and words[0].startswith("/"):  # RouterOS menu paths: "/system/reboot" = "/system reboot"
        words = [part for part in words[0].split("/") if part] + words[1:]
    while words and words[0] == "do":
        words = words[1:]
    return words


def split_commands(line: str) -> list[str]:
    return [part for part in _SPLIT.split(line) if part.strip()]


def _abbr(word: str, keyword: str) -> bool:
    return bool(word) and keyword.startswith(word)


def _matches(words: list[str], keywords: tuple[str, ...]) -> bool:
    return len(words) >= len(keywords) and all(_abbr(w, k) for w, k in zip(words, keywords, strict=False))


def denied(command: str, extra: Iterable[tuple[tuple[str, ...], str]] = ()) -> str | None:
    """The denylist rule a single command breaks, or None. ``extra``: the driver's own rules (Driver.denylist())."""
    words = words_of(command)
    if not words:
        return None
    for keywords, label in [*DENYLIST, *extra]:
        if _matches(words, keywords):
            return f"'{label}' is never sent by NetConfig Studio"
    if _abbr(words[0], "copy"):
        # Only "copy running-config startup-config" is allowed; copying from a file or the network
        # into the running or startup configuration is not.
        if not (len(words) == 3 and _abbr(words[1], "running-config") and _abbr(words[2], "startup-config")
                and len(words[1]) >= 3 and len(words[2]) >= 3):
            return "only 'copy running-config startup-config' is allowed"
    return None


def check_denylist(commands: Iterable[str], extra: Iterable[tuple[tuple[str, ...], str]] = ()) -> list[Violation]:
    extra = list(extra)
    out = []
    for i, line in enumerate(commands):
        for part in split_commands(line):
            rule = denied(part, extra)
            if rule:
                out.append(Violation(i, line, rule))
                break
    return out


# -------------------------------------------------------- management protection
def _mgmt_vlan(name: str | None) -> int | None:
    m = re.fullmatch(r"vlan(\d+)", (name or "").lower())
    return int(m.group(1)) if m else None


def _vlan_ids(text: str) -> set[int]:
    out: set[int] = set()
    for part in text.split(","):
        a, _, b = part.partition("-")
        if a.isdigit() and (not b or b.isdigit()):
            out.update(range(int(a), int(b or a) + 1))
    return out


def _trunk_drops_vlan(args: list[str], vlan: int) -> bool:
    """True when 'switchport trunk allowed vlan <args>' would leave ``vlan`` out."""
    mode, rest = args[0], "".join(args[1:])
    if mode in ("add", "all"):
        return False
    if mode in ("remove", "except"):
        return vlan in _vlan_ids(rest)
    if mode == "none":
        return True
    return vlan not in _vlan_ids("".join(args))


def check_management(
    commands: Iterable[str],
    *,
    mgmt_interface: str | None,
    mgmt_ip: str | None,
    via_ssh: bool,
    normalize_interface: Callable[[str], str],
    uplinks: Iterable[str] = (),
) -> list[Violation]:
    """Block commands that would cut the connection NetConfig Studio is using.

    ``mgmt_interface`` is known only on the device (``show ip interface brief`` in the pre-checks); in a
    preview it is None and only the VTY/SSH rules apply. ``uplinks`` are the ports that carry the
    management VLAN (pre-checks, Phase 3A).
    """
    mgmt = mgmt_interface.lower() if mgmt_interface else None
    mgmt_vlan = _mgmt_vlan(mgmt_interface)
    uplink_set = {u.lower() for u in uplinks}
    out: list[Violation] = []
    context: tuple[str, str] | None = None  # ("interface", name) | ("vty", "") | ("other", "")

    def flag(i: int, line: str, rule: str) -> None:
        out.append(Violation(i, line, rule))

    for i, line in enumerate(commands):
        for part in split_commands(line):
            w = words_of(part)
            if not w:
                continue
            if w[0] in ("exit", "end", "quit", "return"):  # "quit"/"return": Huawei VRP
                context = None
                continue
            if len(w) >= 2 and len(w[0]) >= 2 and _abbr(w[0], "interface"):
                if _abbr(w[1], "range"):
                    context = ("interface", "*range*")
                else:
                    context = ("interface", normalize_interface("".join(w[1:])).lower())
                continue
            if len(w) >= 2 and (_abbr(w[0], "line") or w[0] == "user-interface") and _abbr(w[1], "vty"):
                context = ("vty", "")
                continue
            if len(w) >= 2 and w[0] == "management" and _abbr(w[1], "ssh"):  # Arista EOS
                context = ("mgmt-ssh", "")
                continue
            sub_mode = w[0] == "ip" and len(w) > 1 and w[1] in ("dhcp", "access-list")
            if w[0] in ("router", "vlan", "archive", "dhcp-server") or sub_mode:
                context = ("other", "")

            negated = w[0] in ("no", "undo")  # "undo": Huawei VRP
            body = w[1:] if negated else w

            # Global rules
            if negated and body and len(body[0]) >= 2 and _abbr(body[0], "interface") and mgmt:
                if normalize_interface("".join(body[1:])).lower() == mgmt:
                    flag(i, line, "removes the management interface")
            if negated and body and body[0] == "vlan" and mgmt_vlan and mgmt_vlan in _vlan_ids("".join(body[1:])):
                flag(i, line, "deletes the management VLAN")
            if via_ssh and negated and len(body) >= 2 and _abbr(body[0], "line") and _abbr(body[1], "vty"):
                flag(i, line, "removes the VTY lines used by SSH")
            if via_ssh and negated and len(body) >= 2 and body[0] == "ip" and body[1] == "ssh":
                flag(i, line, "changes SSH while connected over SSH")
            if via_ssh and negated and len(body) >= 2 and body[0] == "ssh" and body[1] == "server":  # AOS-CX
                flag(i, line, "turns off the SSH server while connected over SSH")
            if via_ssh and w[0] == "undo" and body[:1] in (["stelnet"], ["ssh"]):  # Huawei VRP
                flag(i, line, "changes SSH while connected over SSH")
            if via_ssh and context and context[0] == "mgmt-ssh" and not negated and len(w[0]) >= 2 \
                    and _abbr(w[0], "shutdown"):
                flag(i, line, "turns off the SSH server while connected over SSH")

            if context and context[0] == "vty" and via_ssh:
                transport = len(body) >= 2 and len(body[0]) >= 3 and _abbr(body[0], "transport") \
                    and _abbr(body[1], "input")
                if transport:
                    if negated or "ssh" not in body[2:]:
                        flag(i, line, "removes SSH access on the VTY lines while connected over SSH")
                if negated and body and len(body[0]) >= 3 and _abbr(body[0], "login"):
                    flag(i, line, "removes the login method used by SSH")
                if body[:2] == ["protocol", "inbound"] and (negated or not {"ssh", "all"} & set(body[2:])):
                    flag(i, line, "removes SSH access on the VTY lines while connected over SSH")  # Huawei VRP

            if context and context[0] == "interface":
                name = context[1]
                is_mgmt = mgmt is not None and (name == mgmt or name == "*range*")
                is_uplink = name in uplink_set or (name == "*range*" and bool(uplink_set))
                if is_mgmt or is_uplink:
                    if not negated and len(w[0]) >= 2 and _abbr(w[0], "shutdown"):
                        what = "interface" if is_mgmt else "uplink"
                        flag(i, line, f"shuts down the management {what}")
                if is_mgmt:
                    if negated and len(body) >= 2 and body[0] == "ip" and _abbr(body[1], "address"):
                        flag(i, line, "removes the management IP address")
                    if not negated and len(body) >= 3 and body[0] == "ip" and _abbr(body[1], "address") \
                            and mgmt_ip and body[2].split("/")[0] != mgmt_ip:
                        flag(i, line, "changes the management IP address")
                    vrf = body[:1] == ["vrf"] and len(body) >= 2 and _abbr(body[1], "forwarding")
                    ip_vrf = body[:2] == ["ip", "vrf"] and len(body) >= 3 and _abbr(body[2], "forwarding")
                    if not negated and (vrf or ip_vrf):
                        flag(i, line, "moves the management interface into another VRF")
                if is_uplink and mgmt_vlan:
                    if not negated and len(body) >= 4 and _abbr(body[0], "switchport") and _abbr(body[1], "access") \
                            and _abbr(body[2], "vlan") and body[3].isdigit() and int(body[3]) != mgmt_vlan:
                        flag(i, line, f"moves the management uplink out of VLAN {mgmt_vlan}")
                    if not negated and len(body) >= 5 and _abbr(body[0], "switchport") and _abbr(body[1], "trunk") \
                            and _abbr(body[2], "allowed") and _abbr(body[3], "vlan") \
                            and _trunk_drops_vlan(body[4:], mgmt_vlan):
                        flag(i, line, f"removes management VLAN {mgmt_vlan} from the uplink trunk")

            # Assigning the management IP to another interface creates a duplicate address.
            if mgmt_ip and not negated and len(body) >= 3 and body[0] == "ip" and _abbr(body[1], "address") \
                    and body[2].split("/")[0] == mgmt_ip and context and context[0] == "interface" and mgmt \
                    and context[1] != mgmt:
                flag(i, line, "puts the management IP address on another interface")
    # One message per command line is enough.
    seen: set[int] = set()
    return [v for v in out if not (v.index in seen or seen.add(v.index))]


def management_violations(driver, commands: list[str], *, mgmt_interface: str | None, mgmt_ip: str | None,
                          via_ssh: bool) -> list[Violation]:
    """Management protection in the syntax of the driver's OS."""
    if driver.cli_syntax == "set":
        return check_management_set(commands, mgmt_interface=mgmt_interface, mgmt_ip=mgmt_ip, via_ssh=via_ssh)
    if driver.cli_syntax == "routeros":
        return check_management_routeros(commands, mgmt_interface=mgmt_interface, mgmt_ip=mgmt_ip, via_ssh=via_ssh)
    if driver.cli_syntax == "dlink":
        return check_management_dlink(commands, mgmt_interface=mgmt_interface, via_ssh=via_ssh)
    return check_management(commands, mgmt_interface=mgmt_interface, mgmt_ip=mgmt_ip, via_ssh=via_ssh,
                            normalize_interface=driver.normalize_interface)


def check_management_set(commands: Iterable[str], *, mgmt_interface: str | None, mgmt_ip: str | None,
                         via_ssh: bool) -> list[Violation]:
    """Junos "set" syntax. ``mgmt_interface`` is a logical interface such as "ge-0/0/0.0", "irb.10" or "em0.0".

    Blocked: disabling or deactivating the management port or unit, turning the management port into a switch
    port, putting it into an interface range (a range applies its settings to every member), another address on
    the management unit, the management address on another interface, deactivating system settings, and changing
    SSH while connected over SSH. "delete" is on the global denylist, so nothing can be removed."""
    phys, _, unit = (mgmt_interface or "").lower().partition(".")
    unit = unit or "0"
    out: list[Violation] = []

    def address_in(rest: list[str]) -> str | None:
        if "address" in rest and rest.index("address") + 1 < len(rest):
            return rest[rest.index("address") + 1].split("/")[0]
        return None

    def rule_for(w: list[str]) -> str | None:
        if len(w) < 2 or w[0] not in ("set", "deactivate"):
            return None
        if w[0] == "deactivate" and w[1] == "system":
            return "deactivates system settings (SSH, users) while connected"
        if via_ssh and w[1:4] == ["system", "services", "ssh"] and w[0] == "deactivate":
            return "changes SSH while connected over SSH"
        if w[1] != "interfaces" or len(w) < 3:
            return None
        name, rest = w[2], w[3:]
        this_unit = rest[1] if rest[:1] == ["unit"] and len(rest) > 1 else None
        addr = address_in(rest)
        if phys and name == "interface-range" and phys in rest:
            return "puts the management port into an interface range"
        if phys and name == phys:
            if w[0] == "deactivate" or ("disable" in rest and this_unit in (None, unit)):
                return "disables the management interface"
            if "ethernet-switching" in rest:
                return "turns the management port into a switch port"
            if addr and this_unit == unit and mgmt_ip and addr != mgmt_ip:
                return "adds another address to the management interface"
        if mgmt_ip and addr == mgmt_ip and f"{name}.{this_unit}" != f"{phys}.{unit}":
            return "puts the management IP address on another interface"
        return None

    for i, line in enumerate(commands):
        for part in split_commands(line):
            rule = rule_for(words_of(part))
            if rule:
                out.append(Violation(i, line, rule))
                break
    return out


def _violations(commands: Iterable[str], rule_for: Callable[[list[str]], str | None]) -> list[Violation]:
    out = []
    for i, line in enumerate(commands):
        for part in split_commands(line):
            rule = rule_for(words_of(part))
            if rule:
                out.append(Violation(i, line, rule))
                break
    return out


def check_management_routeros(commands: Iterable[str], *, mgmt_interface: str | None, mgmt_ip: str | None,
                              via_ssh: bool) -> list[Violation]:
    """MikroTik RouterOS (experimental). ``mgmt_interface`` is the interface that holds the management address
    ("bridge", "ether1"). Blocked: "remove"/"unset" anywhere (RouterOS deletes with them), disabling the
    management interface or changing its VLAN settings, changing IP addresses or reusing the management
    address, and turning off or moving the SSH service while connected over SSH."""
    mgmt = (mgmt_interface or "").lower()

    def rule_for(w: list[str]) -> str | None:
        tokens = {t.strip("[]") for t in w}
        if {"remove", "unset"} & tokens:
            return "removes configuration ('remove' and 'unset' are never sent to RouterOS)"
        names = {t.split("=", 1)[1] for t in tokens if t.startswith(("interface=", "name="))}
        on_mgmt = bool(mgmt) and (mgmt in names or (w[:2] == ["interface", "disable"] and mgmt in tokens))
        if on_mgmt and ("disable" in tokens or "disabled=yes" in tokens):
            return "disables the management interface"
        if on_mgmt and any(t.startswith(("pvid=", "frame-types=", "bridge=", "vlan-id=")) for t in tokens):
            return "changes the VLAN settings of the management interface"
        if w[:2] == ["ip", "address"]:
            if mgmt_ip and any(t.startswith("address=") and t[8:].split("/")[0] == mgmt_ip for t in tokens):
                return "puts the management IP address on another interface"
            if on_mgmt or "set" in tokens or "disable" in tokens:
                return "changes the IP addresses of the management interface"
        if via_ssh and w[:2] == ["ip", "service"] and "ssh" in tokens and (
                "disable" in tokens or any(t.startswith(("disabled=y", "port=", "address=")) for t in tokens)):
            return "changes the SSH service while connected over SSH"
        return None

    return _violations(commands, rule_for)


def check_management_dlink(commands: Iterable[str], *, mgmt_interface: str | None, via_ssh: bool) -> list[Violation]:
    """D-Link DGS/DES CLI (experimental). ``mgmt_interface`` is "Vlan<N>", the VLAN of the System IP interface.
    Blocked: any "config ipif" (the management address), turning SSH off while connected over SSH, disabling
    ports (the port that carries the management traffic is not known) and removing ports from the management
    VLAN."""
    mgmt_vlan = _mgmt_vlan(mgmt_interface)

    def rule_for(w: list[str]) -> str | None:
        if w[:2] == ["config", "ipif"]:
            return "changes the management IP interface"
        if via_ssh and w[:2] == ["disable", "ssh"]:
            return "turns off SSH while connected over SSH"
        if w[:2] == ["config", "ports"] and "disable" in w:
            return "disables switch ports (the management port is not known)"
        if w[:2] == ["config", "vlan"] and "delete" in w and mgmt_vlan is not None:
            vid = w[3] if w[2:3] == ["vlanid"] and len(w) > 3 else ("1" if w[2:3] == ["default"] else None)
            if vid is not None and mgmt_vlan in _vlan_ids(vid):
                return f"removes ports from management VLAN {mgmt_vlan}"
        return None

    return _violations(commands, rule_for)
