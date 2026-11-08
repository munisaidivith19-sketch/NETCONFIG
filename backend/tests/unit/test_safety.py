"""docs/TEST_PLAN.md 3.3 – denylist and management-interface protection."""

import pytest

from app.drivers.base import ModelInfo
from app.drivers.cisco_ios import CiscoIos
from app.services.safety import check_denylist, check_management, denied

NORM = CiscoIos(ModelInfo(id="x", name="x", category="switch")).normalize_interface

BLOCKED = [
    # every denylist entry
    "reload", "erase startup-config", "write erase", "delete flash:x", "format flash:", "copy tftp: startup-config",
    "no username admin", "crypto key zeroize", "request system zeroize", "request system reboot", "debug all",
    "configure replace flash:old.cfg",
    # abbreviations
    "rel", "relo", "wr er", "era start", "del flash:x", "cry key zero rsa", "req sys reboot", "deb all",
    # do prefix
    "do reload", "DO  wr  erase", "do rel", "do do reload",
    # case and spacing
    "  RELOAD", "Reload", "write    erase", "write\terase", "\treload in 5",
    # ambiguous short words fail closed
    "de flash:x", "re", "e", "f",
    # copy into a configuration from anywhere else
    "copy http://10.0.0.1/x running-config", "copy flash:a.cfg startup-config", "copy run tftp:", "c r s",
]
ALLOWED = [
    "no shutdown", "description reload-test", "vlan 10", " name delete_me", "ip domain name format.lab",
    "hostname reloader", "interface GigabitEthernet1/0/1", "exit", "end", "write memory", "wr",
    "copy running-config startup-config", "copy run start", "do show running-config", "no username-x",
    "debug ip packet",  # only "debug all" is on the agreed list
    "no ip http server", "service password-encryption", "crypto key generate rsa modulus 2048",
]


@pytest.mark.parametrize("command", BLOCKED)
def test_blocked(command):
    assert denied(command), command
    v = check_denylist(["vlan 10", command])
    assert len(v) == 1 and v[0].index == 1 and v[0].command == command


@pytest.mark.parametrize("command", ALLOWED)
def test_allowed(command):
    assert denied(command) is None, command


@pytest.mark.parametrize("line", ["vlan 10 ; reload", "hostname a | reload", "name x\nreload", "exit && reload",
                                  "name x\r\nrel", "vlan 10;do reload"])
def test_several_commands_on_one_line(line):
    assert check_denylist([line]), line


# ------------------------------------------------------------- management
def mgmt(commands, **kw):
    args = {"mgmt_interface": "Vlan1", "mgmt_ip": "10.0.0.2", "via_ssh": True, "normalize_interface": NORM,
            "uplinks": ["GigabitEthernet1/0/24"]} | kw
    return check_management(commands, **args)


@pytest.mark.parametrize("commands", [
    ["interface Vlan1", " shutdown"],
    ["int vlan1", "shut"],
    ["interface Vlan 1", " sh"],
    ["interface Vlan1", " ip address 10.0.0.3 255.255.255.0"],
    ["interface Vlan1", " no ip address"],
    ["interface Vlan1", " vrf forwarding MGMT"],
    ["no interface Vlan1"],
    ["no vlan 1"],
    ["interface GigabitEthernet1/0/24", " switchport access vlan 20"],
    ["interface gi1/0/24", " shutdown"],
    ["interface GigabitEthernet1/0/24", " switchport trunk allowed vlan 10,20"],
    ["interface GigabitEthernet1/0/24", " switchport trunk allowed vlan remove 1"],
    ["interface range GigabitEthernet1/0/20 - 24", " shutdown"],
    ["line vty 0 4", " transport input none"],
    ["line vty 0 15", " transport input telnet"],
    ["line vty 0 4", " no transport input"],
    ["line vty 0 4", " no login"],
    ["no line vty 5 15"],
    ["interface Vlan20", " ip address 10.0.0.2 255.255.255.0"],
    ["do interface Vlan1", "do shutdown"],
])
def test_management_blocked(commands):
    assert mgmt(commands), commands


@pytest.mark.parametrize("commands", [
    ["interface Vlan20", " shutdown"],
    ["interface Vlan1", " no shutdown"],
    ["interface Vlan1", " ip address 10.0.0.2 255.255.255.0"],
    ["interface Vlan1", " description Management"],
    ["interface GigabitEthernet1/0/1", " shutdown"],
    ["interface GigabitEthernet1/0/24", " switchport trunk allowed vlan 1,10,20"],
    ["interface GigabitEthernet1/0/24", " switchport trunk allowed vlan add 30"],
    ["interface GigabitEthernet1/0/24", " switchport access vlan 1"],
    ["line vty 0 4", " transport input ssh"],
    ["line vty 0 4", " login local"],
    ["no vlan 20"],
    ["interface Vlan1", "exit", "shutdown"],  # back in global mode: not the interface
])
def test_management_allowed(commands):
    assert mgmt(commands) == [], commands


def test_vty_rules_only_over_ssh():
    assert mgmt(["line vty 0 4", " transport input none"], via_ssh=False) == []


def test_preview_without_known_mgmt_interface_still_checks_vty():
    v = mgmt(["interface Vlan1", " shutdown", "line vty 0 4", " transport input none"],
             mgmt_interface=None, uplinks=[])
    assert [x.index for x in v] == [3]


def test_one_violation_per_line():
    v = mgmt(["interface Vlan1", " shutdown"])
    assert len(v) == 1 and v[0].index == 1 and "management" in v[0].message
