"""Arista EOS, Juniper Junos and Aruba AOS-CX drivers (Phase 4A): secrets, review errors, parsers, error
patterns, management protection and denylists. Golden command files are in tests/golden/<os_id>/."""

import re

import pytest

from app.drivers.arista_eos import AristaEos
from app.drivers.aruba_aoscx import ArubaAoscx
from app.drivers.base import ModelInfo
from app.drivers.juniper_junos import JuniperJunos, parse_terse
from app.models.plan import ConfigPlan
from app.security.masking import mask_lines
from app.services import safety
from app.services.catalog import load_file
from app.services.push import find_error

MODELS = {m["_id"]: m for m in load_file()["models"]}
EOS = AristaEos(ModelInfo.from_doc(MODELS["arista-ceos-lab"]))
JUNOS = JuniperJunos(ModelInfo.from_doc(MODELS["juniper-vjunos-switch"]))
SRX = JuniperJunos(ModelInfo.from_doc(MODELS["juniper-srx300"]))
CX = ArubaAoscx(ModelInfo.from_doc(MODELS["aruba-cx-simulator"]))
SSH = {"ssh": {"username": "netadmin", "password": "Lab-Pass-2026"}}


def plan(data):
    return ConfigPlan.model_validate(data)


@pytest.mark.parametrize("drv", [EOS, JUNOS, CX], ids=lambda d: d.os_id)
def test_password_only_in_push_and_masked_in_records(drv):
    preview = "\n".join(drv.generate(plan(SSH), "preview"))
    push = drv.generate(plan(SSH), "push")
    assert "Lab-Pass-2026" not in preview and "********" in preview
    if drv is JUNOS:
        line = next(c for c in push if "encrypted-password" in c)
        assert re.search(r'encrypted-password "\$6\$[./0-9A-Za-z]{16}\$[./0-9A-Za-z]{86}"$', line)
        assert "Lab-Pass-2026" not in "\n".join(push)  # Junos gets a hash, never the password
    else:
        assert any("Lab-Pass-2026" in c for c in push)
    assert "Lab-Pass-2026" not in "\n".join(mask_lines(push))
    assert not any(c.endswith('"$6$') for c in mask_lines(push))


def test_junos_hash_never_left_unmasked():
    masked = mask_lines(JUNOS.generate(plan(SSH), "push"))
    assert any(c.endswith("encrypted-password ********") for c in masked)


@pytest.mark.parametrize(("drv", "data", "path"), [
    (JUNOS, {"vlans": [{"id": 10, "name": "default"}]}, "vlans.0.name"),
    (JUNOS, {"trunks": [{"interface": "ge-0/0/1", "allowed_vlans": [10], "native_vlan": 99}]}, "trunks.0.native_vlan"),
    (JUNOS, {"svis": [{"vlan": 10, "ip": "10.0.10.1/24"}]}, "svis.0.vlan"),
    (JUNOS, {"custom_commands": ["show version"]}, "custom_commands.0"),
    (JUNOS, {"nat": {"inside_interfaces": ["ge-0/0/1"], "outside_interface": "ge-0/0/0",
                     "inside_networks": ["10.0.0.0/24"]}}, "nat"),
    (CX, {"revert_minutes": 90}, "revert_minutes"),
    (CX, {"ssh": {"username": "admin"}}, "ssh.username"),
    (CX, {"ssh": {"username": "NetAdmin"}}, "ssh.username"),
    (EOS, {"dhcp": [{"name": "P", "network": "10.0.0.0/24", "default_router": "10.0.0.1"}]}, "dhcp.0.network"),
    (EOS, {"hardening": {"banner": "hello"}}, "hardening.banner"),
])
def test_review_names_the_field(drv, data, path):
    errors, _ = drv.review(plan(data))
    assert path in errors, errors


def test_srx_allows_nat_and_dhcp_warns_about_zones():
    data = {"interfaces": [{"interface": "ge-0/0/1", "ip": "10.0.0.1/24"}],
            "dhcp": [{"name": "LAN", "network": "10.0.0.0/24", "default_router": "10.0.0.1"}],
            "nat": {"inside_interfaces": ["ge-0/0/1"], "outside_interface": "ge-0/0/0",
                    "inside_networks": ["10.0.0.0/24"]}}
    errors, notes = SRX.review(plan(data))
    assert not errors and any("host-inbound-traffic" in n for n in notes)


def test_dhcp_range_skips_excluded_and_router():
    data = {"interfaces": [{"interface": "ge-0/0/1", "ip": "10.0.30.1/24"}],
            "dhcp": [{"name": "G", "network": "10.0.30.0/24", "default_router": "10.0.30.1",
                      "excluded": [{"start": "10.0.30.2", "end": "10.0.30.20"}, {"start": "10.0.30.100"}]}]}
    out = JUNOS.generate(plan(data), "preview")
    assert "set access address-assignment pool G family inet range R1 low 10.0.30.101" in out
    assert "set access address-assignment pool G family inet range R1 high 10.0.30.254" in out
    assert any("largest free block" in n for n in JUNOS.review(plan(data))[1])


@pytest.mark.parametrize(("drv", "text"), [
    (EOS, "% Invalid input (at token 1: 'foo')"), (EOS, "% Incomplete command"),
    (EOS, "% Maximum number of pending sessions has been reached"),
    (JUNOS, "syntax error, expecting <statement>."), (JUNOS, "error: configuration check-out failed"),
    (JUNOS, "    unknown command."), (CX, "Invalid input: 12"), (CX, "% Command incomplete."),
])
def test_error_patterns(drv, text):
    assert find_error(drv, f"cmd\n{text}") == text.strip()


@pytest.mark.parametrize(("drv", "text"), [
    (JUNOS, "warning: uncommitted changes will be discarded on exit"),
    (CX, 'switch# WARNING Please "checkpoint auto confirm" within 2 minutes'),
    (EOS, "! Interface does not exist. The configuration will not take effect until the module is inserted."),
])
def test_informational_lines(drv, text):
    assert find_error(drv, text) is None


def test_junos_management_interface_from_terse():
    terse = """Interface               Admin Link Proto    Local                 Remote
ge-0/0/0                up    up
ge-0/0/0.0              up    up   eth-switch
irb                     up    up
irb.99                  up    up   inet     10.10.99.2/24
                                            10.10.99.3/24
em0.0                   up    up   inet     192.168.122.10/24
"""
    assert JUNOS.management_interface({"show interfaces terse": terse}, "10.10.99.3") == "irb.99"
    assert JUNOS.management_interface({"show interfaces terse": terse}, "192.168.122.10") == "em0.0"
    assert parse_terse(terse)["irb.99"]["addresses"] == ["10.10.99.2/24", "10.10.99.3/24"]


@pytest.mark.parametrize(("command", "blocked"), [
    ("set interfaces ge-0/0/0 disable", True),
    ("set interfaces ge-0/0/0 unit 0 disable", True),
    ("deactivate interfaces ge-0/0/0", True),
    ("set interfaces ge-0/0/0 unit 0 family ethernet-switching interface-mode access", True),
    ("set interfaces interface-range R member ge-0/0/0", True),
    ("set interfaces interface-range R member-range ge-0/0/1 to ge-0/0/3", True),  # may hold the mgmt port
    ("set interfaces interface-range R member ge-0/0/*", True),
    ("set interfaces interface-range R member ge-0/0/5", False),
    ("set interfaces ge-0/0/0 unit 0 family inet address 10.9.9.9/24", True),
    ("set interfaces ge-0/0/5 unit 0 family inet address 10.0.0.2/24", True),
    ("set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.2/24", False),
    ("set interfaces ge-0/0/1 disable", False),
    ("set interfaces ge-0/0/0 description uplink", False),
    ("deactivate system services ssh", True),
])
def test_junos_management_protection(command, blocked):
    found = safety.management_violations(JUNOS, [command], mgmt_interface="ge-0/0/0.0", mgmt_ip="10.0.0.2",
                                         via_ssh=True)
    assert bool(found) == blocked, found


@pytest.mark.parametrize(("command", "blocked"), [
    ("interface Ethernet1\n   ip address 10.0.0.9/24", True),
    ("interface Ethernet1\n   ip address 10.0.0.2/24", False),
    ("interface Ethernet1\n   shutdown", True),
    ("management ssh\n   shutdown", True),
    ("management ssh\n   idle-timeout 5", False),
])
def test_eos_management_protection(command, blocked):
    found = safety.management_violations(EOS, command.split("\n"), mgmt_interface="Ethernet1", mgmt_ip="10.0.0.2",
                                         via_ssh=True)
    assert bool(found) == blocked, found


def test_aoscx_management_interface_and_protection():
    run = ("hostname sw1\ninterface mgmt\n    ip static 192.168.1.10/24\n"
           "interface vlan 99\n    ip address 10.0.99.2/24\n")
    assert CX.management_interface({"show running-config": run}, "10.0.99.2") == "Vlan99"
    assert CX.management_interface({"show running-config": run}, "192.168.1.10") == "mgmt"
    found = safety.management_violations(CX, ["interface vlan 99", "    shutdown"], mgmt_interface="Vlan99",
                                         mgmt_ip="10.0.99.2", via_ssh=True)
    assert found
    assert safety.management_violations(CX, ["no ssh server vrf default"], mgmt_interface="Vlan99",
                                        mgmt_ip="10.0.99.2", via_ssh=True)
    # The out-of-band port is addressed with "ip static" (Phase 4D review): changing or removing it is blocked.
    for change in (["interface mgmt", "    ip static 192.168.1.99/24"], ["interface mgmt", "    no ip static"]):
        assert safety.management_violations(CX, change, mgmt_interface="mgmt", mgmt_ip="192.168.1.10",
                                            via_ssh=True), change
    assert not safety.management_violations(CX, ["interface mgmt", "    ip static 192.168.1.10/24"],
                                            mgmt_interface="mgmt", mgmt_ip="192.168.1.10", via_ssh=True)


@pytest.mark.parametrize(("drv", "command"), [
    (JUNOS, "commit"), (JUNOS, "rollback 1"), (JUNOS, "load override terminal"), (JUNOS, "delete interfaces"),
    (JUNOS, "request system reboot"), (JUNOS, "exit configuration-mode"),
    (EOS, "configure session x abort"), (EOS, "commit"), (EOS, "reload now"),
    (CX, "checkpoint rollback startup-config"), (CX, "erase checkpoint all"), (CX, "no user netadmin"),
    # Phase 4D security review: shells, leaving the EOS session, Junos configuration groups
    (EOS, "bash sudo shutdown -r now"), (EOS, "end"), (CX, "start-shell"),
    (JUNOS, "set groups G interfaces ge-0/0/0 disable"), (JUNOS, "set apply-groups G"),
    # Phase 5B security review: features that run a stored command later
    (EOS, "event-handler x"), (EOS, "schedule x interval 1 max-log-files 1 command bash sudo reboot"),
    (EOS, "alias x bash"), (EOS, "daemon x"), (EOS, "do event-handler x"),
    (JUNOS, "set event-options policy p events e then execute-commands commands x"),
    (JUNOS, "set system scripts op file x.slax"),
    (CX, "job j1"), (CX, "schedule s1"), (CX, "alias x boot system"),
])
def test_driver_denylist(drv, command):
    assert safety.check_denylist([command], drv.denylist())


@pytest.mark.parametrize("drv", [EOS, JUNOS, CX], ids=lambda d: d.os_id)
def test_eigrp_is_not_a_capability(drv):
    assert "eigrp" not in drv.capabilities


def test_check_reports_missing_statements():
    p = plan({"vlans": [{"id": 10, "name": "Sales"}, {"id": 20, "name": "Eng"}]})
    checks = JUNOS.check(p, {"show configuration | display set": "set vlans Sales vlan-id 10\n"})
    failed = [c for c in checks if not c.ok]
    assert failed and "set vlans Eng vlan-id 20" in failed[0].detail
    eos = EOS.check(p, {"show running-config": "vlan 10\n   name Sales\n", "show vlan": "10    Sales   active\n"})
    assert [c.name for c in eos if not c.ok] == ["configured: vlan 20", "VLAN 20 Eng active"]


def test_facts_and_neighbors_parsers():
    v = "Arista cEOSLab\nHardware version:\nSerial number: ABC123\nSoftware image version: 4.30.1F\n"
    assert EOS.parse_facts({"show version": v, "show hostname": "Hostname: sw1\nFQDN: sw1"}) == {
        "model": "cEOSLab", "version": "4.30.1F", "serial": "ABC123", "hostname": "sw1"}
    j = "Hostname: vsw1\nModel: ex9214\nJunos: 23.2R1.14\n"
    assert JUNOS.parse_facts({"show version": j})["model"] == "ex9214"
    s = "Hostname          : cx1\nProduct Name      : JL659A 6300M 48SR5\nChassis Serial Nbr: SG0000\n" \
        "AOS-CX Version    : FL.10.10.0001\n"
    facts = CX.parse_facts({"show system": s})
    assert facts["serial"] == "SG0000" and facts["version"] == "FL.10.10.0001" and facts["model"].startswith("JL659A")
    lldp = "Port                           : 1/1/1\nNeighbor Chassis-Name          : core1\n" \
           "Neighbor Port-ID               : 1/1/4\nNeighbor Management-Address    : 10.0.0.1\n"
    assert CX.parse_neighbors({"show lldp neighbor-info detail": lldp}) == [
        {"local": "1/1/1", "remote": "core1", "port": "1/1/4", "ip": "10.0.0.1", "protocol": "lldp"}]


def test_junos_start_shell_is_denied():
    junos = JuniperJunos(ModelInfo(id="x", name="x", category="switch"))
    assert safety.denied("start shell sh", junos.denylist())
    assert safety.denied("sta sh", junos.denylist())


def test_hidden_default_line_still_fails_when_a_conflicting_line_is_present():
    from app.drivers.arista_eos import EOS_HIDDEN_DEFAULTS, parse_running_config
    from app.drivers.common import section_checks
    cmds = ["interface Ethernet1", "   switchport mode access"]
    ok = parse_running_config("interface Ethernet1\n   description x\n!\n")
    bad = parse_running_config("interface Ethernet1\n   switchport mode trunk\n!\n")
    assert all(c.ok for c in section_checks(cmds, ok, EOS_HIDDEN_DEFAULTS))
    assert not all(c.ok for c in section_checks(cmds, bad, EOS_HIDDEN_DEFAULTS))
