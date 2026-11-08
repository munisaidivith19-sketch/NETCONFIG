import pytest

from app.security.masking import MASK, mask_lines, mask_text

CASES = [
    ("username admin privilege 15 secret 9 $9$abcDEF123", "username admin privilege 15 secret 9 " + MASK),
    ("enable secret 5 $1$xyz$abc", "enable secret 5 " + MASK),
    ("username bob password 7 0822455D0A16", "username bob password 7 " + MASK),
    ("snmp-server community public RO", "snmp-server community " + MASK + " RO"),
    (" key-string 7 0822455D0A16", " key-string 7 " + MASK),
    ('set system root-authentication encrypted-password "$6$abc"',
     "set system root-authentication encrypted-password " + MASK),
    ('set security ike policy p pre-shared-key ascii-text "s3cret"',
     "set security ike policy p pre-shared-key ascii-text " + MASK),
    ("crypto isakmp key 0 MyKey address 1.2.3.4", "crypto isakmp key 0 " + MASK + " address 1.2.3.4"),
    ("ENABLE SECRET topsecret", "ENABLE SECRET " + MASK),
]


@pytest.mark.parametrize("raw,expected", CASES)
def test_masks_secret_value_and_keeps_keyword(raw, expected):
    assert mask_text(raw) == expected


def test_keeps_non_secret_lines():
    for line in ["service password-encryption", "no service password-encryption", "hostname core-sw1",
                 "interface GigabitEthernet1/0/1"]:
        assert mask_text(line) == line


def test_idempotent_and_multiline():
    text = "enable secret abc\nusername u secret 9 $9$x\nhostname a"
    once = mask_text(text)
    assert mask_text(once) == once
    assert "abc" not in once and "$9$x" not in once and "hostname a" in once


def test_mask_lines():
    assert mask_lines(["enable secret x", "vlan 10"]) == ["enable secret " + MASK, "vlan 10"]
