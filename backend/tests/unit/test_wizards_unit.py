"""Pure parts of the Phase 3B wizards: link addressing, side matching, bootstrap plans, job aggregation."""

import pytest
from pydantic import SecretStr, ValidationError

from app.models.job import JobCreate, RunRequest
from app.models.plan import ConfigPlan
from app.models.wizards import BootstrapSpec
from app.services.connection import ConnectFailed, ConnectParams, open_netmiko
from app.services.jobs import aggregate
from app.services.wizards import bootstrap_plan, link_addresses, link_match

OID = "a" * 24


def test_link_addresses():
    assert link_addresses("10.255.0.0/30") == ("10.255.0.1", "10.255.0.2", 30)
    assert link_addresses("10.255.0.0/31") == ("10.255.0.0", "10.255.0.1", 31)  # RFC 3021


def side(ip, area=0, rid="1.1.1.1"):
    return ConfigPlan.model_validate({
        "interfaces": [{"interface": "GigabitEthernet0/1", "ip": ip}],
        "routing": {"ospf": {"process_id": 1, "router_id": rid,
                             "interfaces": [{"interface": "GigabitEthernet0/1", "area": area}]}}})


def test_link_match_ok_and_mismatch():
    good = link_match(side("10.255.0.1/30"), side("10.255.0.2/30", rid="2.2.2.2"), ("r1", "r2"))
    assert all(c["ok"] for c in good)
    bad = {c["name"]: c["ok"] for c in link_match(side("10.255.0.1/30"), side("10.255.0.6/30", area=1), ("r1", "r2"))}
    assert bad["Different OSPF router IDs"] is False and bad["Same OSPF area (0)"] is False
    assert any(not ok for name, ok in bad.items() if name.startswith("Same subnet"))


def test_bootstrap_plan_switch_and_router():
    spec = BootstrapSpec.model_validate({"hostname": "sw9", "domain": "lab.example.net", "admin_username": "netadmin",
                                         "mgmt": {"vlan": 99, "ip": "10.10.10.2/24", "gateway": "10.10.10.1"}})
    plan, errors = bootstrap_plan(spec, "switch")
    assert not errors and plan.default_gateway == "10.10.10.1" and plan.vlans[0].id == 99
    assert plan.ssh.set_enable_secret and plan.save and plan.hardening is not None
    plan, errors = bootstrap_plan(spec, "router")
    assert plan is None and "bootstrap.mgmt.interface" in errors
    _, errors = bootstrap_plan(spec, "ap")
    assert "device_id" in errors


def test_aggregate():
    assert aggregate(["success", "success"]) == "success"
    assert aggregate(["success", "rolled_back"]) == "failed"  # partly applied
    assert aggregate(["rolled_back", "cancelled"]) == "rolled_back"
    assert aggregate(["blocked"]) == "blocked"
    assert aggregate(["cancelled", "cancelled"]) == "cancelled"


def test_job_create_kind():
    assert JobCreate.model_validate({"device_id": OID, "plan": {}}).kind == "push"
    assert JobCreate.model_validate({"device_ids": [OID, "b" * 24], "plan": {}}).kind == "multi"
    with pytest.raises(ValidationError):
        JobCreate.model_validate({"device_id": OID})


def test_run_request_login_rules():
    with pytest.raises(ValidationError):
        RunRequest.model_validate({"username": "netops"})  # password missing
    with pytest.raises(ValidationError):
        RunRequest.model_validate({"logins": [{"device_id": OID, "username": "a", "password": "x"}] * 2})
    req = RunRequest.model_validate({"username": "netops", "password": "Pw-1",
                                     "logins": [{"device_id": OID, "username": "other", "password": "Pw-2"}]})
    assert req.login_for(OID)[0] == "other" and req.login_for("b" * 24)[0] == "netops"
    assert {s.get_secret_value() for s in req.all_secrets()} == {"Pw-1", "Pw-2"}


def test_ssh_never_opened_without_login():
    with pytest.raises(ConnectFailed) as exc:
        open_netmiko(ConnectParams(method="ssh", device_type="cisco_ios", host="10.0.0.2", port=22,
                                   username=None, password=None))
    assert exc.value.kind == "auth"
    with pytest.raises(ConnectFailed):
        open_netmiko(ConnectParams(method="ssh", device_type="cisco_ios", host="10.0.0.2", port=22,
                                   username="netops", password=None, secret=SecretStr("x")))
