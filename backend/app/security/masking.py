"""Mask secrets in generated commands, device output and config backups (CLAUDE.md 8.3)."""

import re

MASK = "********"

# keyword [optional type digit/word] <secret>. The keyword and type stay visible; the secret is hidden.
_PATTERNS = [
    # Cisco / Arista / Aruba: password|secret [0|5|7|8|9|sha512|ciphertext|plaintext] value
    re.compile(
        r"(?P<keep>\b(?:password|secret)\s+"
        r"(?:(?:0|5|6|7|8|9|sha512|sha256|ciphertext|plaintext|irreversible-cipher|cipher|simple)\s+)?)"
        r"(?P<val>\S+)",
        re.IGNORECASE,
    ),
    re.compile(r"(?P<keep>\bcommunity\s+)(?P<val>\S+)", re.IGNORECASE),
    # MikroTik RouterOS "/user add ... password=X"; D-Link "config account U encrypt plain_text|sha_1 X"
    re.compile(r"(?P<keep>\bpassword=)(?P<val>\"[^\"]*\"|\S+)", re.IGNORECASE),
    re.compile(r"(?P<keep>\bencrypt\s+(?:plain_text|sha_1)\s+)(?P<val>\S+)", re.IGNORECASE),
    re.compile(r"(?P<keep>\bkey-string\s+(?:\d\s+)?)(?P<val>\S+)", re.IGNORECASE),
    # "... key 0|6|7 X"; not "message-digest-key 7 md5 X" (handled below, the 7 there is a key id).
    # AOS-CX writes "key ciphertext|plaintext X" (radius-server / tacacs-server host).
    re.compile(r"(?P<keep>(?<!-)\bkey\s+(?:0|6|7|ciphertext|plaintext)\s+)(?P<val>\S+)", re.IGNORECASE),
    # Junos: encrypted-password "..." / pre-shared-key ascii-text "..."
    re.compile(r"(?P<keep>\bencrypted-password\s+)(?P<val>\"[^\"]*\"|\S+)", re.IGNORECASE),
    re.compile(
        r"(?P<keep>\bpre-shared-key\s+(?:(?:ascii-text|hexadecimal|plaintext|ciphertext)\s+)?(?:\d\s+)?)"
        r"(?P<val>\"[^\"]*\"|\S+)",
        re.IGNORECASE,
    ),
    # Junos authentication-key "..."; Cisco "ip ospf authentication-key [7] X", "ntp authentication-key 1 md5 X";
    # AOS-CX "ntp authentication-key 1 md5|sha1 ciphertext|plaintext X"
    re.compile(r"(?P<keep>\bauthentication-key\s+"
               r"(?:\d+\s+(?:md5|sha1)\s+(?:(?:\d|ciphertext|plaintext)\s+)?|[07]\s+)?)(?P<val>\"[^\"]*\"|\S+)",
               re.IGNORECASE),
    # Shared keys a running config can hold in clear text (no "password"/"secret" word on the line):
    # tacacs-server|radius-server [host <ip> ...] key [0|7] X
    re.compile(r"(?P<keep>\b(?:tacacs|radius)-server\b.*?\bkey\s+(?:(?:\d|ciphertext|plaintext)\s+)?)(?P<val>\S+)",
               re.IGNORECASE),
    # " key [0|7] X" inside a "tacacs server" / "radius server" block (also a key-chain key id: harmless)
    re.compile(r"(?P<keep>^\s+key\s+(?:(?:\d|ciphertext|plaintext)\s+)?)(?P<val>\S+)", re.IGNORECASE | re.MULTILINE),
    re.compile(r"(?P<keep>\bcrypto\s+isakmp\s+key\s+(?:\d\s+)?)(?P<val>\S+)", re.IGNORECASE),
    # ip ospf message-digest-key 1 md5 [7] X
    re.compile(r"(?P<keep>\bmessage-digest-key\s+\d+\s+md5\s+(?:\d\s+)?)(?P<val>\S+)", re.IGNORECASE),
    # snmp-server host <ip> [traps|informs] [version 1|2c|3 auth|noauth|priv] <community or v3 user>
    re.compile(r"(?P<keep>\bsnmp-server\s+host\s+\S+\s+(?:(?:traps|informs)\s+)?"
               r"(?:version\s+(?:1|2c|3\s+(?:auth|noauth|priv))\s+)?)"
               r"(?P<val>\S+)", re.IGNORECASE),
    # snmp-server user ... auth sha X priv aes 128 Y;
    # AOS-CX "snmpv3 user U auth sha auth-pass ciphertext X priv aes priv-pass ciphertext Y"
    re.compile(r"(?P<keep>\b(?:auth\s+(?:md5|sha\d*)(?:\s+auth-pass)?|priv\s+(?:des|3des|aes(?:\s+\d+)?)"
               r"(?:\s+priv-pass)?)\s+(?:(?:ciphertext|plaintext)\s+)?)(?P<val>\S+)",
               re.IGNORECASE),
    re.compile(r"(?P<keep>\bwpa-psk\s+(?:ascii|hex)\s+(?:\d\s+)?)(?P<val>\S+)", re.IGNORECASE),
]

# Words that follow "password"/"secret" but are not secrets (e.g. "service password-encryption").
_NOT_SECRETS = {MASK, "encryption", "-encryption"}


def _replace(match: re.Match) -> str:
    value = match.group("val")
    if value.lower() in _NOT_SECRETS or value.startswith(MASK):
        return match.group(0)
    return match.group("keep") + MASK


def _mask_line(line: str) -> str:
    for pattern in _PATTERNS:
        line = pattern.sub(_replace, line)
    return line


def mask_text(text: str) -> str:
    """Mask line by line: "\\s+" in a pattern must never run on into the next line (" key 1\\n  key-string ...")."""
    if not text:
        return text
    return "".join(_mask_line(line) for line in text.splitlines(keepends=True))


def mask_lines(lines: list[str]) -> list[str]:
    return [mask_text(line) for line in lines]
