"""Mask secrets in generated commands, device output and config backups (CLAUDE.md 8.3)."""

import re

MASK = "********"

# keyword [optional type digit/word] <secret>. The keyword and type stay visible; the secret is hidden.
_PATTERNS = [
    # Cisco / Arista / Aruba: password|secret [0|5|7|8|9|sha512|ciphertext|plaintext] value
    re.compile(
        r"(?P<keep>\b(?:password|secret)\s+(?:(?:0|5|6|7|8|9|sha512|sha256|ciphertext|plaintext)\s+)?)(?P<val>\S+)",
        re.IGNORECASE,
    ),
    re.compile(r"(?P<keep>\bcommunity\s+)(?P<val>\S+)", re.IGNORECASE),
    re.compile(r"(?P<keep>\bkey-string\s+(?:\d\s+)?)(?P<val>\S+)", re.IGNORECASE),
    re.compile(r"(?P<keep>\bkey\s+(?:0|6|7)\s+)(?P<val>\S+)", re.IGNORECASE),
    # Junos: encrypted-password "..." / pre-shared-key ascii-text "..."
    re.compile(r"(?P<keep>\bencrypted-password\s+)(?P<val>\"[^\"]*\"|\S+)", re.IGNORECASE),
    re.compile(
        r"(?P<keep>\bpre-shared-key\s+(?:(?:ascii-text|hexadecimal|plaintext|ciphertext)\s+)?(?:\d\s+)?)"
        r"(?P<val>\"[^\"]*\"|\S+)",
        re.IGNORECASE,
    ),
    re.compile(r"(?P<keep>\bauthentication-key\s+)(?P<val>\"[^\"]*\"|\S+)", re.IGNORECASE),
]

# Words that follow "password"/"secret" but are not secrets (e.g. "service password-encryption").
_NOT_SECRETS = {MASK, "encryption", "-encryption"}


def _replace(match: re.Match) -> str:
    value = match.group("val")
    if value.lower() in _NOT_SECRETS or value.startswith(MASK):
        return match.group(0)
    return match.group("keep") + MASK


def mask_text(text: str) -> str:
    if not text:
        return text
    out = text
    for pattern in _PATTERNS:
        out = pattern.sub(_replace, out)
    return out


def mask_lines(lines: list[str]) -> list[str]:
    return [mask_text(line) for line in lines]
