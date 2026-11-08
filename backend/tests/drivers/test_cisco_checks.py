"""check(), error_patterns() and management_interface() against recorded sample outputs.

The samples in tests/golden/cisco_ios/outputs/ follow the formats shown in Cisco documentation
(docs/drivers/cisco_ios.md) and are replaced with real lab output in Phase 3B.
"""

import re
from pathlib import Path

import pytest

from app.drivers.base import ModelInfo
from app.drivers.cisco_ios import CiscoIos, parse_interfaces_status
from app.models.plan import ConfigPlan

from .test_golden import MODELS, load_case

OUT = Path(__file__).resolve().parent.parent / "golden" / "cisco_ios" / "outputs"


def sample(name: str) -> str:
    return (OUT / f"{name}.txt").read_text(encoding="utf-8")


def campus_outputs() -> dict[str, str]:
    return {
        "show running-config": sample("show_running_config"),
        "show ip ssh": sample("show_ip_ssh"),
        "show vlan brief": sample("show_vlan_brief"),
        "show interfaces status": sample("show_interfaces_status"),
        "show interfaces TenGigabitEthernet1/1/1 switchport": sample("show_interfaces_te1_1_1_switchport"),
        "show ip interface brief": sample("show_ip_interface_brief"),
        "show ip dhcp pool": sample("show_ip_dhcp_pool"),
        "show ip ospf interface brief": sample("show_ip_ospf_interface_brief"),
        "show ip ospf neighbor": sample("show_ip_ospf_neighbor"),
    }


def failed(checks):
    return [c.name for c in checks if c.required and not c.ok]


def test_full_campus_passes_on_matching_output():
    driver, _, plan = load_case("cisco_ios", "full_campus")
    outputs = campus_outputs()
    assert set(driver.verify_commands(plan)) == set(outputs)
    checks = driver.check(plan, outputs)
    assert failed(checks) == []
    # Vlan99 is up/down in the sample: informational only, it does not fail the push.
    vlan99 = next(c for c in checks if c.name == "Vlan99 up/up")
    assert not vlan99.ok and not vlan99.required


@pytest.mark.parametrize(("command", "old", "new", "expect_failed"), [
    ("show vlan brief", "10   Staff", "10   Sales", "VLAN 10 Staff"),
    ("show vlan brief", "99   Mgmt                             active", "", "VLAN 99 Mgmt"),
    ("show interfaces status", "Gi1/0/3                         connected    20",
     "Gi1/0/3                         connected    1 ", "GigabitEthernet1/0/3 access VLAN 20"),
    ("show interfaces TenGigabitEthernet1/1/1 switchport", "Trunking VLANs Enabled: 10,20,99",
     "Trunking VLANs Enabled: 10,20", "TenGigabitEthernet1/1/1 allowed VLANs"),
    ("show interfaces TenGigabitEthernet1/1/1 switchport", "Native Mode VLAN: 99", "Native Mode VLAN: 1",
     "TenGigabitEthernet1/1/1 native VLAN 99"),
    ("show interfaces TenGigabitEthernet1/1/1 switchport", "Administrative Mode: trunk",
     "Administrative Mode: static access", "TenGigabitEthernet1/1/1 is a trunk"),
    ("show ip interface brief", "10.10.20.1      YES", "10.10.21.1      YES", "Vlan20 address 10.10.20.1"),
    ("show ip ssh", "SSH Enabled - version 2.0", "SSH Disabled - version 1.99", "SSH version 2 enabled"),
    ("show running-config", "hostname campus-core1", "hostname Switch", "hostname campus-core1"),
    ("show running-config", " transport input ssh\nline vty 5 15", " transport input telnet ssh\nline vty 5 15",
     "VTY lines: login local, SSH only"),  # Telnet allowed as well → not "SSH only"
    ("show running-config", "line vty 5 15\n exec-timeout 10 0\n login local\n transport input ssh",
     "line vty 5 15\n exec-timeout 10 0\n login local\n transport input telnet", "VTY lines: login local, SSH only"),
    ("show running-config", "no ip http server\n", "", "HTTP server disabled"),
    ("show running-config", "ip route 0.0.0.0 0.0.0.0 10.255.1.2", "", "static route 0.0.0.0/0"),
    ("show ip dhcp pool", "Pool GUESTS :", "", "DHCP pool GUESTS"),
    ("show ip ospf interface brief", "Vl99         1     0", "Vl99         1     1", "OSPF on Vlan99 area 0"),
])
def test_check_detects_each_difference(command, old, new, expect_failed):
    driver, _, plan = load_case("cisco_ios", "full_campus")
    outputs = campus_outputs()
    assert old in outputs[command], f"sample text not found: {old!r}"
    outputs[command] = outputs[command].replace(old, new)
    bad = failed(driver.check(plan, outputs))
    if expect_failed is None:
        assert bad == []
    else:
        assert expect_failed in bad


def test_missing_output_fails_closed():
    driver, _, plan = load_case("cisco_ios", "full_campus")
    outputs = campus_outputs()
    del outputs["show vlan brief"]
    assert "output of 'show vlan brief'" in failed(driver.check(plan, outputs))
    assert failed(driver.check(plan, {})) == ["output of 'show running-config'"]


def test_router_checks_nat_bgp():
    driver, _, nat_plan = load_case("cisco_ios", "nat_overload_acl")
    nat = sample("show_ip_nat_statistics")
    brief = ("Interface              IP-Address      OK? Method Status                Protocol\n"
             "GigabitEthernet0/0/0   203.0.113.2     YES manual up                    up\n"
             "GigabitEthernet0/0/1   10.0.0.1        YES manual up                    up\n")
    outputs = {"show ip nat statistics": nat, "show ip interface brief": brief}
    assert failed(driver.check(nat_plan, outputs)) == []
    swapped = nat.replace("Outside interfaces:\n  GigabitEthernet0/0/0\nInside interfaces:\n  GigabitEthernet0/0/1",
                          "Outside interfaces:\n  GigabitEthernet0/0/1\nInside interfaces:\n  GigabitEthernet0/0/0")
    assert set(failed(driver.check(nat_plan, {**outputs, "show ip nat statistics": swapped}))) == {
        "NAT inside GigabitEthernet0/0/1", "NAT outside GigabitEthernet0/0/0"}

    driver, _, bgp_plan = load_case("cisco_ios", "bgp_ebgp_neighbor")
    bgp = sample("show_ip_bgp_summary")
    outputs = {"show ip bgp summary": bgp, "show ip interface brief": brief}
    checks = driver.check(bgp_plan, outputs)
    assert failed(checks) == []
    assert next(c for c in checks if c.name == "BGP 203.0.113.1 established").ok
    idle = bgp.replace("00:21:43        1", "00:00:05     Idle")
    checks = driver.check(bgp_plan, {**outputs, "show ip bgp summary": idle})
    assert failed(checks) == []  # a session still coming up is informational
    assert not next(c for c in checks if c.name == "BGP 203.0.113.1 established").ok
    wrong_as = bgp.replace("4        64500", "4        64501")
    bad = failed(driver.check(bgp_plan, {**outputs, "show ip bgp summary": wrong_as}))
    assert "BGP neighbour 203.0.113.1 AS 64500" in bad


def test_eigrp_check_uses_running_config():
    driver, _, plan = load_case("cisco_ios", "eigrp_named_or_classic")
    run = ("router eigrp 100\n network 10.0.0.0 0.0.0.255\n network 10.255.0.0 0.0.0.3\n"
           " passive-interface GigabitEthernet0/1\n eigrp router-id 10.255.255.3\n")
    outputs = {"show running-config": run, "show ip eigrp neighbors": sample("show_ip_eigrp_neighbors")}
    assert failed(driver.check(plan, outputs)) == []
    without = run.replace(" network 10.255.0.0 0.0.0.3\n", "")
    assert "EIGRP network 10.255.0.0/30" in failed(driver.check(plan, {**outputs, "show running-config": without}))


ERROR_SAMPLES = [
    "                ^\n% Invalid input detected at '^' marker.",
    "% Incomplete command.",
    "% Ambiguous command:  \"sh\"",
    "% Unknown command or computer name, or unable to find computer address",
    "% Bad mask 0xFFFFFF01 for address 10.0.0.1",
    "% Inconsistent address and mask",
    "% 10.0.10.0 overlaps with Vlan20",
    "% Invalid VLAN list",
    "Command rejected: Bad VLAN list - character #1 is a non-numeric",
]
INFO_SAMPLES = [
    "% Access VLAN does not exist. Creating vlan 30",
    "%LINK-3-UPDOWN: Interface GigabitEthernet1/0/1, changed state to up",
    "% Warning: portfast should only be enabled on ports connected to a single host.",
]


@pytest.mark.parametrize("text", ERROR_SAMPLES)
def test_error_patterns_match_documented_errors(text):
    driver = CiscoIos(ModelInfo.from_doc(MODELS["cisco-iosv"]))
    assert any(re.search(p, text) for p in driver.error_patterns())


@pytest.mark.parametrize("text", INFO_SAMPLES)
def test_informational_lines_are_not_errors(text):
    driver = CiscoIos(ModelInfo.from_doc(MODELS["cisco-iosv"]))
    assert not any(re.search(p, text) for p in driver.error_patterns())
    assert any(re.search(p, text) for p in driver.info_patterns())


def test_management_interface_found_by_ip():
    driver = CiscoIos(ModelInfo.from_doc(MODELS["cisco-c9300-24t"]))
    outputs = {"show ip interface brief": sample("show_ip_interface_brief")}
    assert driver.management_interface(outputs, "10.255.1.1") == "TenGigabitEthernet1/1/2"
    assert driver.management_interface(outputs, "10.10.99.1") == "Vlan99"
    assert driver.management_interface(outputs, "192.0.2.1") is None


def test_interfaces_status_name_with_spaces():
    driver = CiscoIos(ModelInfo.from_doc(MODELS["cisco-c9300-24t"]))
    rows = parse_interfaces_status(sample("show_interfaces_status"), driver.normalize_interface)
    assert rows["GigabitEthernet1/0/4"] == {"status": "notconnect", "vlan": "1"}
    assert rows["TenGigabitEthernet1/1/1"]["vlan"] == "trunk"


@pytest.mark.parametrize(("raw", "full"), [
    ("gi1/0/1", "GigabitEthernet1/0/1"), ("Gi 0/1", "GigabitEthernet0/1"), ("te1/1/1", "TenGigabitEthernet1/1/1"),
    ("fa0/1", "FastEthernet0/1"), ("vl10", "Vlan10"), ("Vlan10", "Vlan10"), ("lo0", "Loopback0"),
    ("po1", "Port-channel1"), ("tw1/0/1", "TwoGigabitEthernet1/0/1"),
    ("f0/1", "f0/1"), ("t1/0/1", "t1/0/1"),  # ambiguous: left unchanged so the port check fails
])
def test_normalize_interface(raw, full):
    assert CiscoIos(ModelInfo(id="x", name="x", category="switch")).normalize_interface(raw) == full


def test_vlan_list_format():
    from app.drivers.base import expand_vlan_list, vlan_list
    assert vlan_list([30, 10, 31, 32, 20, 21]) == "10,20,21,30-32"
    assert expand_vlan_list("10,20-22\n 30") == {10, 20, 21, 22, 30}
    plan = ConfigPlan.model_validate({"trunks": [{"interface": "Gi0/1", "allowed_vlans": [1, 2, 3]}]})
    assert plan.trunks[0].allowed_vlans == [1, 2, 3]
