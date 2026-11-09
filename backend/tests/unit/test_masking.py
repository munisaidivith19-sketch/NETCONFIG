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
    # Shared keys a running-config backup holds in clear text (Phase 3C security review)
    ("tacacs-server key Tac4csKey", "tacacs-server key " + MASK),
    ("radius-server host 10.1.1.1 auth-port 1645 acct-port 1646 key 7 0822455D0A16",
     "radius-server host 10.1.1.1 auth-port 1645 acct-port 1646 key 7 " + MASK),
    (" key 0 RadKey123", " key 0 " + MASK),  # inside "radius server X" / "tacacs server X"
    (" key Plain-Tac-Key", " key " + MASK),
    ("crypto isakmp key IkePsk address 1.2.3.4", "crypto isakmp key " + MASK + " address 1.2.3.4"),
    (" ip ospf message-digest-key 1 md5 OspfKey", " ip ospf message-digest-key 1 md5 " + MASK),
    (" ip ospf message-digest-key 7 md5 7 0822455D0A16", " ip ospf message-digest-key 7 md5 7 " + MASK),
    (" ip ospf authentication-key 7 0822455D0A16", " ip ospf authentication-key 7 " + MASK),
    ("ntp authentication-key 1 md5 NtpKey 7", "ntp authentication-key 1 md5 " + MASK + " 7"),
    ("snmp-server host 10.1.1.5 version 2c TrapComm", "snmp-server host 10.1.1.5 version 2c " + MASK),
    ("snmp-server host 10.1.1.5 TrapComm", "snmp-server host 10.1.1.5 " + MASK),
    ("snmp-server user u1 g1 v3 auth sha AuthPass1 priv aes 128 PrivPass1",
     "snmp-server user u1 g1 v3 auth sha " + MASK + " priv aes 128 " + MASK),
    (" wpa-psk ascii 0 WifiKey123", " wpa-psk ascii 0 " + MASK),
]


@pytest.mark.parametrize("raw,expected", CASES)
def test_masks_secret_value_and_keeps_keyword(raw, expected):
    assert mask_text(raw) == expected


def test_keeps_non_secret_lines():
    for line in ["service password-encryption", "no service password-encryption", "hostname core-sw1",
                 "interface GigabitEthernet1/0/1", "crypto key generate rsa modulus 2048",
                 "tacacs-server directed-request", "ip ospf authentication message-digest"]:
        assert mask_text(line) == line


def test_idempotent_and_multiline():
    text = "enable secret abc\nusername u secret 9 $9$x\nhostname a"
    once = mask_text(text)
    assert mask_text(once) == once
    assert "abc" not in once and "$9$x" not in once and "hostname a" in once


def test_never_masks_across_a_line_break():
    # " key 1" (a key-chain key id) must not swallow the newline and mask the next line's keyword.
    # The id itself is masked (harmless, see the pattern's comment); the next line's keyword survives.
    text = "key chain K\n key 1\n  key-string 7 ABC\r\n key 2\n\n  key-string 0 DEF\n"
    assert mask_text(text) == (f"key chain K\n key {MASK}\n  key-string 7 {MASK}\r\n key {MASK}\n\n"
                               f"  key-string 0 {MASK}\n")


def test_mask_lines():
    assert mask_lines(["enable secret x", "vlan 10"]) == ["enable secret " + MASK, "vlan 10"]
