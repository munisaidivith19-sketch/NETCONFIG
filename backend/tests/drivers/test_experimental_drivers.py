"""Experimental drivers (Phase 4A): MikroTik RouterOS, Huawei VRP, D-Link DGS, TP-Link JetStream. Golden command
files are in tests/golden/<os_id>/; these tests cover gating, secrets, safety rules, parsers and checks."""

import pytest

from app.config import Settings
from app.drivers.base import ModelInfo
from app.drivers.experimental.dlink_ds import DlinkDs, parse_show_vlan
from app.drivers.experimental.huawei_vrp import HuaweiVrp, allow_pass
from app.drivers.experimental.mikrotik_routeros import MikrotikRouteros
from app.drivers.experimental.tplink_jetstream import TplinkJetstream
from app.drivers.registry import EXPERIMENTAL, driver_class
from app.models.plan import ConfigPlan
from app.security.masking import mask_lines
from app.services import safety
from app.services.catalog import load_file
from app.services.push import find_error

MODELS = {m["_id"]: m for m in load_file()["models"]}
MT = MikrotikRouteros(ModelInfo.from_doc(MODELS["mikrotik-crs326-24g-2s"]))
HW = HuaweiVrp(ModelInfo.from_doc(MODELS["huawei-s5735-l24t4s-a"]))
DL = DlinkDs(ModelInfo.from_doc(MODELS["dlink-dgs-1210-28"]))
TP = TplinkJetstream(ModelInfo.from_doc(MODELS["tplink-tl-sg2210p"]))
ALL = [MT, HW, DL, TP]
SSH = {"ssh": {"username": "netadmin", "password": "Lab-Pass-2026"}}


def plan(data):
    return ConfigPlan.model_validate(data)


def test_loaded_only_with_the_flag():
    off, on = Settings(enable_experimental_drivers=False), Settings(enable_experimental_drivers=True)
    for os_id in ("mikrotik_routeros", "huawei_vrp", "dlink_ds", "tplink_jetstream"):
        assert os_id in EXPERIMENTAL
        assert driver_class(os_id, off) is None
        assert driver_class(os_id, on) is EXPERIMENTAL[os_id]
    catalog = {d["_id"]: d for d in load_file()["os_drivers"]}
    assert all(catalog[os_id]["support"] == "experimental" for os_id in EXPERIMENTAL)


@pytest.mark.parametrize("drv", ALL, ids=lambda d: d.os_id)
def test_no_rollback_timer_and_failure_needs_a_person(drv):
    sess = drv.session(plan({}), "x")
    assert sess.strategy == "backup_restore" and not sess.timer and not sess.revert
    assert drv.rollback_strategy() == "backup_restore"
    assert any("no automatic rollback" in n for n in drv.review(plan({}))[1])


@pytest.mark.parametrize("drv", ALL, ids=lambda d: d.os_id)
def test_password_only_in_push_and_masked_in_records(drv):
    assert "Lab-Pass-2026" not in "\n".join(drv.generate(plan(SSH), "preview"))
    push = drv.generate(plan(SSH), "push")
    assert any("Lab-Pass-2026" in c for c in push)
    assert "Lab-Pass-2026" not in "\n".join(mask_lines(push))


def test_push_without_password_is_refused():
    with pytest.raises(ValueError, match="ssh.password"):
        HW.generate(plan({"ssh": {"username": "netadmin"}}), "push")


@pytest.mark.parametrize("drv", ALL, ids=lambda d: d.os_id)
def test_unsupported_options_are_errors_not_skipped(drv):
    errors, _ = drv.review(plan({"hardening": {}, "ssh": {"username": "netadmin", "set_enable_secret": True,
                                                           "regenerate_keys": True}}))
    assert {"hardening.login_block", "ssh.set_enable_secret", "ssh.regenerate_keys"} <= set(errors)
    assert "ospf" not in drv.capabilities and "eigrp" not in drv.capabilities


def test_specific_review_rules():
    long_name = {"vlans": [{"id": 10, "name": "A-very-long-vlan-name-x"}]}
    assert "vlans.0.name" in DL.review(plan(long_name))[0]  # D-Link: 20 characters
    assert "vlans.0.name" not in TP.review(plan(long_name))[0]
    trunk = {"vlans": [{"id": 10, "name": "A"}], "trunks": [{"interface": "ether24", "allowed_vlans": [10, 30]}]}
    assert "trunks.0.allowed_vlans" in MT.review(plan(trunk))[0]  # VLAN 30 has no bridge VLAN entry
    pw16 = {"ssh": {"username": "netadmin", "password": "Sixteen-chars-pw"}}
    assert "ssh.password" in DL.review(plan(pw16))[0]
    assert "ssh.password" not in HW.review(plan(pw16))[0]


def test_huawei_allow_pass_groups_ranges_ten_per_command():
    assert allow_pass([10, 20, 30, 31, 32]) == ["10 20 30 to 32"]
    assert allow_pass(list(range(2, 40, 2))) == [" ".join(str(v) for v in range(2, 22, 2)),
                                                 " ".join(str(v) for v in range(22, 40, 2))]


def test_huawei_save_answers_the_question_and_undo_is_a_negation():
    assert HW.prompts("save") == [(r"\[Y/N\]", "y")] and HW.prompts("sysname x") is None
    found = safety.management_violations(HW, ["interface Vlanif1", " shutdown"], mgmt_interface="Vlan1",
                                         mgmt_ip="10.0.0.2", via_ssh=True)
    assert found
    for cmd in (["undo stelnet server enable"], ["user-interface vty 0 4", " protocol inbound telnet"],
                ["user-interface vty 0 4", " undo protocol inbound ssh"]):
        assert safety.management_violations(HW, cmd, mgmt_interface=None, mgmt_ip=None, via_ssh=True), cmd
    ok = HW.generate(plan(SSH), "preview")
    assert not safety.management_violations(HW, ok, mgmt_interface="Vlan1", mgmt_ip="10.0.0.2", via_ssh=True)


def test_huawei_management_interface_and_check():
    brief = "Interface                         IP Address/Mask      Physical   Protocol\n" \
            "MEth0/0/1                         192.168.1.253/24     up         up\n" \
            "Vlanif1                           10.0.0.2/24          up         up\n"
    assert HW.management_interface({"display ip interface brief": brief}, "10.0.0.2") == "Vlan1"
    assert HW.management_interface({"display ip interface brief": brief}, "192.168.1.253") == "MEth0/0/1"
    p = plan({"vlans": [{"id": 10, "name": "Sales"}],
              "access": [{"interfaces": ["GigabitEthernet0/0/2"], "vlan": 10, "portfast": False}]})
    good = "#\nsysname sw1\n#\nvlan batch 10\n#\nvlan 10\n name Sales\n#\ninterface GigabitEthernet0/0/2\n" \
           " port link-type access\n port default vlan 10\n#\nreturn\n"
    assert all(c.ok for c in HW.check(p, {"display current-configuration": good}))
    bad = good.replace(" port default vlan 10\n", "")
    failed = [c for c in HW.check(p, {"display current-configuration": bad}) if not c.ok]
    assert failed and "port default vlan 10" in failed[0].detail


@pytest.mark.parametrize(("command", "blocked"), [
    ("/system reboot", True), ("/system/reboot", True), ("/SYSTEM RESET-CONFIGURATION", True),
    ("/interface bridge vlan remove 0", True), ("/ip address remove [find]", True), ("/import file=x.rsc", True),
    ("/interface ethernet set [find name=ether1] disabled=yes", True),
    ("/interface bridge port set [find interface=ether1] pvid=20", True),
    ("/ip address add address=10.0.0.2/24 interface=ether5", True),
    ("/ip service set ssh disabled=yes", True), ("/ip service set ssh port=2222", True),
    ("/interface bridge port set [find interface=ether2] pvid=20", False),
    ("/ip service set telnet disabled=yes", False), ("/system identity set name=sw1", False),
])
def test_routeros_safety(command, blocked):
    found = safety.check_denylist([command], MT.denylist()) + safety.management_violations(
        MT, [command], mgmt_interface="ether1", mgmt_ip="10.0.0.2", via_ssh=True)
    assert bool(found) == blocked, found


def test_routeros_parsers_and_checks():
    addrs = " 0   address=10.0.0.2/24 network=10.0.0.0 interface=bridge actual-interface=bridge\n"
    assert MT.management_interface({"/ip address print terse": addrs}, "10.0.0.2") == "bridge"
    p = plan({"basic": {"hostname": "sw1"}, "vlans": [{"id": 10, "name": "Sales"}],
              "access": [{"interfaces": ["ether2"], "vlan": 10, "portfast": False}],
              "trunks": [{"interface": "ether24", "allowed_vlans": [10]}]})
    outputs = {"/system identity print": "  name: sw1",
               "/interface bridge print terse": " 0 R name=bridge mtu=auto vlan-filtering=yes",
               "/interface bridge vlan print terse":
                   " 0   bridge=bridge vlan-ids=10 tagged=ether24 untagged=ether2 current-tagged=ether24",
               "/interface bridge port print terse": " 0 interface=ether2 bridge=bridge pvid=10\n"
                                                     " 1 interface=ether24 bridge=bridge pvid=1"}
    assert [c.name for c in MT.check(p, outputs) if not c.ok] == []
    outputs["/interface bridge vlan print terse"] = " 0 bridge=bridge vlan-ids=10 untagged=ether2"
    assert [c.name for c in MT.check(p, outputs) if not c.ok] == ["VLAN 10 Sales"]


@pytest.mark.parametrize(("command", "blocked"), [
    ("config ipif System ipaddress 10.0.0.9/24", True), ("disable ssh", True), ("reboot", True),
    ("config ports 1-3 state disable", True), ("config vlan vlanid 1 delete 5", True),
    ("config vlan default delete 5", True), ("create account admin x", True), ("delete vlan vlanid 10", True),
    ("config vlan vlanid 10 delete 5", False), ("config vlan vlanid 10 add untagged 5", False), ("save", False),
])
def test_dlink_safety(command, blocked):
    found = safety.check_denylist([command], DL.denylist()) + safety.management_violations(
        DL, [command], mgmt_interface="Vlan1", mgmt_ip="10.0.0.2", via_ssh=True)
    assert bool(found) == blocked, found


SHOW_VLAN = """Command: show vlan

VID             : 1          VLAN NAME       : default
VLAN Type       : Static
Member Ports    : 1,5-28
Untagged Ports  : 1,5-24

VID             : 10         VLAN NAME       : Sales
VLAN Type       : Static
Member Ports    : 2-4,25
Untagged Ports  : 2-4
"""


def test_dlink_parsers_adapt_and_check():
    vlans = parse_show_vlan(SHOW_VLAN)
    assert vlans[10]["untagged"] == {"2", "3", "4"} and vlans[10]["tagged"] == {"25"}
    ipif = "IP Interface   : System\nVLAN Name      : default\nIP Address     : 10.0.0.2/24\n"
    assert DL.management_interface({"show ipif": ipif, "show vlan": SHOW_VLAN}, "10.0.0.2") == "Vlan1"
    p = plan({"vlans": [{"id": 10, "name": "Sales"}, {"id": 20, "name": "Eng"}],
              "access": [{"interfaces": ["2", "3", "4"], "vlan": 10, "portfast": False}]})
    cmds, notes = DL.adapt_commands(p, DL.generate(p, "preview"), {"show vlan": SHOW_VLAN})
    assert cmds[:2] == ["config vlan vlanid 10 name Sales", "create vlan Eng tag 20"] and notes
    pvid = "Port   PVID\n----   ----\n 2      10\n 3      10\n 4      10\n"
    checks = DL.check(p, {"show vlan": SHOW_VLAN, "show port_vlan pvid": pvid})
    assert [c.name for c in checks if not c.ok] == ["VLAN 20 Eng"]
    leaky = SHOW_VLAN.replace("Member Ports    : 1,5-28", "Member Ports    : 1-28")
    assert "port 2 left VLAN 1" in [c.name for c in DL.check(p, {"show vlan": leaky, "show port_vlan pvid": pvid})
                                    if not c.ok]


def test_tplink_interface_names_check_and_management():
    assert TP.normalize_interface("gigabitEthernet 1/0/3") == "gigabitEthernet1/0/3"
    assert TP.normalize_interface("gi1/0/3") == "gigabitEthernet1/0/3"
    run = '#\nhostname "sw1"\n#\nvlan 10\n name "Sales"\n#\ninterface gigabitEthernet 1/0/2\n' \
          ' switchport general allowed vlan 10 untagged\n switchport pvid 10\n#\ninterface vlan 1\n' \
          ' ip address 10.0.0.2 255.255.255.0\n#\nend\n'
    assert TP.management_interface({"show running-config": run}, "10.0.0.2") == "Vlan1"
    p = plan({"basic": {"hostname": "sw1"}, "vlans": [{"id": 10, "name": "Sales"}],
              "access": [{"interfaces": ["gigabitEthernet1/0/2"], "vlan": 10, "portfast": False}]})
    assert [c.name for c in TP.check(p, {"show running-config": run}) if not c.ok] == []
    found = safety.management_violations(TP, ["interface vlan 1", " shutdown"], mgmt_interface="Vlan1",
                                         mgmt_ip="10.0.0.2", via_ssh=True)
    assert found
    assert safety.check_denylist(["no ip ssh server"], TP.denylist())


@pytest.mark.parametrize(("drv", "text"), [
    (MT, "failure: already have such name"), (MT, "bad command name foo (line 1 column 2)"),
    (MT, "expected end of command (line 1 column 40)"),
    (HW, "Error: Unrecognized command found at '^' position."), (HW, "Error: Wrong parameter found at '^' position."),
    (DL, "Fail!"), (DL, "Next possible completions:"),
    (TP, "Error: Bad command"), (TP, "% Invalid input"),
])
def test_error_patterns(drv, text):
    assert find_error(drv, f"cmd\n{text}")
