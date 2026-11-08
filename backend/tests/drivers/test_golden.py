"""Golden-file tests: plan in tests/golden/<os_id>/<case>.json → exact commands in <case>.txt and
verification commands in <case>.verify.txt.

UPDATE_GOLDEN=1 pytest tests/drivers rewrites the expected files. A human must review the diff –
that review is the point of these tests.
"""

import json
import os
from pathlib import Path

import pytest

from app.drivers.base import ModelInfo, UnsupportedFeature
from app.drivers.cisco_ios import CiscoIos
from app.drivers.registry import CORE
from app.models.plan import ConfigPlan
from app.services import safety
from app.services.catalog import effective_capabilities, load_file
from app.services.validation import normalize_interfaces, validate_plan

GOLDEN = Path(__file__).resolve().parent.parent / "golden"
UPDATE = os.environ.get("UPDATE_GOLDEN") == "1"
CATALOG = load_file()
MODELS = {m["_id"]: m for m in CATALOG["models"]}
DRIVERS = {d["_id"]: d for d in CATALOG["os_drivers"]}

CASES = sorted((os_dir.name, f.stem) for os_dir in GOLDEN.iterdir() if os_dir.is_dir()
               for f in os_dir.glob("*.json"))
REQUIRED_CASES = {"basic_hostname_domain", "ssh_v2", "hardening", "vlans_multi", "access_ports_range",
                  "portfast_portsecurity", "trunk_allowed_native", "svi_ip_routing", "routed_interface",
                  "dhcp_pool_excluded", "nat_overload_acl", "static_routes", "ospf_area0", "eigrp_named_or_classic",
                  "bgp_ebgp_neighbor", "full_campus"}


def load_case(os_id: str, case: str):
    spec = json.loads((GOLDEN / os_id / f"{case}.json").read_text(encoding="utf-8"))
    model = MODELS[spec["model_id"]]
    driver = CORE[os_id](ModelInfo.from_doc(model))
    plan = normalize_interfaces(ConfigPlan.model_validate(spec["plan"]), driver.normalize_interface)
    return driver, model, plan


def compare(path: Path, lines: list[str]) -> None:
    text = "\n".join(lines) + "\n"
    if UPDATE:
        path.write_text(text, encoding="utf-8", newline="\n")
    assert path.exists(), f"{path.name} missing – run UPDATE_GOLDEN=1 pytest tests/drivers and review it"
    assert path.read_text(encoding="utf-8") == text


def test_every_required_case_exists():
    for os_id in CORE:
        have = {case for o, case in CASES if o == os_id}
        assert REQUIRED_CASES <= have, REQUIRED_CASES - have


@pytest.mark.parametrize(("os_id", "case"), CASES)
def test_golden_commands(os_id, case):
    driver, model, plan = load_case(os_id, case)
    caps = set(effective_capabilities(DRIVERS[os_id], model))
    result = validate_plan(plan, model=driver.model, capabilities=caps, os_name=driver.os_name)
    assert result.ok, result.errors  # every golden plan must be valid for its model
    commands = driver.generate(plan, "preview")
    assert safety.check_denylist(commands) == []
    compare(GOLDEN / os_id / f"{case}.txt", commands)
    compare(GOLDEN / os_id / f"{case}.verify.txt", driver.verify_commands(plan))


@pytest.mark.parametrize(("os_id", "case"), CASES)
def test_generated_lines_are_single_commands(os_id, case):
    driver, _, plan = load_case(os_id, case)
    for line in driver.generate(plan, "preview"):
        assert "\n" not in line and "\r" not in line
        assert ";" not in line and "|" not in line
        assert line == line.rstrip()


def test_preview_masks_secrets_push_does_not():
    driver, _, plan = load_case("cisco_ios", "ssh_v2")
    preview = "\n".join(driver.generate(plan, "preview"))
    push = "\n".join(driver.generate(plan, "push"))
    assert "Lab-Pass-2026" not in preview and "Enable-2026x" not in preview
    assert "username netadmin privilege 15 secret ********" in preview
    assert "username netadmin privilege 15 secret Lab-Pass-2026" in push
    assert "enable secret Enable-2026x" in push


def test_push_without_plan_secret_is_refused():
    driver = CiscoIos(ModelInfo.from_doc(MODELS["cisco-iosv"]))
    plan = ConfigPlan.model_validate({"basic": {"hostname": "r1", "domain": "lab.example.net"},
                                      "ssh": {"username": "netadmin"}})
    assert "secret ********" in "\n".join(driver.generate(plan, "preview"))
    with pytest.raises(ValueError, match="ssh.password"):
        driver.generate(plan, "push")


def test_unsupported_feature_raises_not_skipped():
    driver = CiscoIos(ModelInfo.from_doc(MODELS["cisco-iosv"]))
    driver.capabilities = driver.capabilities - {"eigrp"}
    plan = ConfigPlan.model_validate({"routing": {"eigrp": {"asn": 1, "router_id": "1.1.1.1",
                                                            "networks": ["10.0.0.0/24"]}}})
    with pytest.raises(UnsupportedFeature, match="eigrp"):
        driver.generate(plan, "preview")


@pytest.mark.parametrize(("flags", "expected", "absent"), [
    ({"trunk_encapsulation_cmd": True}, " switchport trunk encapsulation dot1q", None),
    ({}, None, " switchport trunk encapsulation dot1q"),
])
def test_trunk_encapsulation_flag(flags, expected, absent):
    driver = CiscoIos(ModelInfo(id="x", name="x", category="switch", flags=flags))
    plan = ConfigPlan.model_validate({"trunks": [{"interface": "GigabitEthernet0/1", "allowed_vlans": [10]}]})
    out = driver.generate(plan, "preview")
    if expected:
        assert out.index(expected) < out.index(" switchport mode trunk")
    if absent:
        assert absent not in out


def test_portfast_edge_and_vty_flags():
    flags = {"portfast_keyword": "edge", "vty_lines": 16}
    driver = CiscoIos(ModelInfo(id="x", name="x", category="switch", flags=flags))
    plan = ConfigPlan.model_validate({
        "basic": {"hostname": "s1", "domain": "lab.example.net"}, "ssh": {"username": "netadmin"},
        "access": [{"interfaces": ["GigabitEthernet1/0/1"], "vlan": 10}]})
    out = driver.generate(plan, "preview")
    assert " spanning-tree portfast edge" in out
    assert "line vty 0 4" in out and "line vty 5 15" in out


def test_session_steps_use_archive_fs_flag():
    driver = CiscoIos(ModelInfo.from_doc(MODELS["cisco-iosv"]))
    steps = driver.session_steps(ConfigPlan.model_validate({"revert_minutes": 7}))
    assert steps["archive"] == ["archive", " path flash0:ncs-archive", " maximum 5"]
    assert steps["begin"] == ["configure terminal revert timer 7"]
    assert steps["confirm"] == ["configure confirm"] and steps["revert"] == ["configure revert now"]
    assert driver.save_command() == "write memory" and driver.rollback_strategy() == "revert_timer"
