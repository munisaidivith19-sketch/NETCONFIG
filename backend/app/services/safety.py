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
    while words and words[0] == "do":
        words = words[1:]
    return words


def split_commands(line: str) -> list[str]:
    return [part for part in _SPLIT.split(line) if part.strip()]


def _abbr(word: str, keyword: str) -> bool:
    return bool(word) and keyword.startswith(word)


def _matches(words: list[str], keywords: tuple[str, ...]) -> bool:
    return len(words) >= len(keywords) and all(_abbr(w, k) for w, k in zip(words, keywords, strict=False))


def denied(command: str) -> str | None:
    """The denylist rule a single command breaks, or None."""
    words = words_of(command)
    if not words:
        return None
    for keywords, label in DENYLIST:
        if _matches(words, keywords):
            return f"'{label}' is never sent by NetConfig Studio"
    if _abbr(words[0], "copy"):
        # Only "copy running-config startup-config" is allowed; copying from a file or the network
        # into the running or startup configuration is not.
        if not (len(words) == 3 and _abbr(words[1], "running-config") and _abbr(words[2], "startup-config")
                and len(words[1]) >= 3 and len(words[2]) >= 3):
            return "only 'copy running-config startup-config' is allowed"
    return None


def check_denylist(commands: Iterable[str]) -> list[Violation]:
    out = []
    for i, line in enumerate(commands):
        for part in split_commands(line):
            rule = denied(part)
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
            if w[0] in ("exit", "end"):
                context = None
                continue
            if len(w) >= 2 and len(w[0]) >= 2 and _abbr(w[0], "interface"):
                if _abbr(w[1], "range"):
                    context = ("interface", "*range*")
                else:
                    context = ("interface", normalize_interface("".join(w[1:])).lower())
                continue
            if len(w) >= 2 and _abbr(w[0], "line") and _abbr(w[1], "vty"):
                context = ("vty", "")
                continue
            sub_mode = w[0] == "ip" and len(w) > 1 and w[1] in ("dhcp", "access-list")
            if w[0] in ("router", "vlan", "archive") or sub_mode:
                context = ("other", "")

            negated = w[0] == "no"
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

            if context and context[0] == "vty" and via_ssh:
                transport = len(body) >= 2 and len(body[0]) >= 3 and _abbr(body[0], "transport") \
                    and _abbr(body[1], "input")
                if transport:
                    if negated or "ssh" not in body[2:]:
                        flag(i, line, "removes SSH access on the VTY lines while connected over SSH")
                if negated and body and len(body[0]) >= 3 and _abbr(body[0], "login"):
                    flag(i, line, "removes the login method used by SSH")

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
                            and mgmt_ip and body[2] != mgmt_ip:
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
                    and body[2] == mgmt_ip and context and context[0] == "interface" and mgmt and context[1] != mgmt:
                flag(i, line, "puts the management IP address on another interface")
    # One message per command line is enough.
    seen: set[int] = set()
    return [v for v in out if not (v.index in seen or seen.add(v.index))]
