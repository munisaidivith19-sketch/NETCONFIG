"""PushEngine scenarios P1–P6, P9–P11, P13 (docs/TEST_PLAN.md section 5) with a fake device session."""

from pydantic import SecretStr

from app.drivers.base import ModelInfo
from app.drivers.cisco_ios import CiscoIos
from app.models.plan import ConfigPlan
from app.services.catalog import load_file
from app.services.connection import ConnectFailed, ConnectParams
from app.services.push import MANUAL, PushEngine, StepInput

from .fake import RSA_KEYS, FakeConnection, FakeConnector

MODELS = {m["_id"]: m for m in load_file()["models"]}
DRIVER = CiscoIos(ModelInfo.from_doc(MODELS["cisco-iosvl2"]))
PASSWORD = SecretStr("Device-Login-Pw-1")
VLAN_PLAN = {"vlans": [{"id": 10, "name": "Sales"}], "revert_minutes": 10}


def params(method="ssh"):
    return ConnectParams(method=method, device_type="cisco_ios", host="10.0.0.2", port=22, username="netops",
                         password=PASSWORD, secret=SecretStr("Enable-Login-Pw-2"))


def run(plan=VLAN_PLAN, fake=None, connector=None, cancelled=lambda: False, mgmt_ip="10.0.0.2"):
    connector = connector or FakeConnector(fake or FakeConnection())
    states = []
    engine = PushEngine(open_connection=lambda p, notes: connector.open(p, notes=notes), on_state=states.append,
                        cancelled=cancelled, sleep=lambda s: None)
    result = engine.run(StepInput(driver=DRIVER, plan=ConfigPlan.model_validate(plan), params=params(),
                                  mgmt_ip=mgmt_ip, secrets=[PASSWORD, SecretStr("Enable-Login-Pw-2")]))
    return result, states, connector.fake


def test_p1_success_order():
    result, states, fake = run()
    assert result.status == "success", result.error
    assert states == ["connecting", "backing_up", "checking", "applying", "verifying", "saving"]
    assert fake.sent == [
        ("show", "show running-config"),
        ("show", "show ip interface brief"),
        ("config_mode", "configure terminal revert timer 10"),
        ("config", "vlan 10"), ("config", " name Sales"),
        ("exit_config", ""),
        ("show", "show vlan brief"),
        ("exec", "configure confirm"),
        ("exec", "write memory"),
    ]
    assert result.mgmt_interface == "Vlan1" and fake.closed >= 1
    assert all(c["ok"] for c in result.checks)


def test_p1_archive_created_when_missing():
    no_archive = "hostname sw1\ninterface Vlan1\n ip address 10.0.0.2 255.255.255.0"
    result, _, fake = run(fake=FakeConnection(responses={"show running-config": no_archive}))
    assert result.status == "success"
    i = fake.sent.index(("config_mode", "configure terminal"))
    assert fake.sent[i + 1:i + 4] == [("config", "archive"), ("config", " path flash0:ncs-archive"),
                                      ("config", " maximum 5")]
    assert fake.sent.index(("config_mode", "configure terminal revert timer 10")) > i


def test_p2_cli_error_stops_and_rolls_back():
    plan = {"vlans": [{"id": 10, "name": "Sales"}, {"id": 20, "name": "Eng"}]}
    fake = FakeConnection(fail_on={" name Sales": "% Invalid input detected at '^' marker."})
    result, states, fake = run(plan, fake)
    assert result.status == "rolled_back"
    assert result.error == {"command": " name Sales", "message": "% Invalid input detected at '^' marker."}
    assert "vlan 20" not in fake.config_sent()  # later commands are never sent
    assert ("exec", "configure revert now") in fake.sent and ("exec", "configure confirm") not in fake.sent
    assert states[-1] == "rolling_back"


def test_informational_lines_are_not_errors():
    fake = FakeConnection(fail_on={"vlan 10": "% Access VLAN does not exist. Creating vlan 10"})
    result, _, _ = run(fake=fake)
    assert result.status == "success"


def test_p3_unreachable_after_apply_relies_on_timer():
    result, _, fake = run(fake=FakeConnection(unreachable_after_apply=True))
    assert result.status == "rolled_back"
    assert any("revert timer" in n for n in result.notes)
    assert ("exec", "configure confirm") not in fake.sent


def test_p3_unreachable_then_reconnect_reverts_now():
    connector = FakeConnector(FakeConnection(unreachable_after_apply=True), reconnect_fails=False)
    result, _, fake = run(connector=connector)
    assert result.status == "rolled_back" and ("exec", "configure revert now") in fake.sent
    assert connector.opens == 2


def test_p4_verification_failure_rolls_back():
    fake = FakeConnection(responses={"show vlan brief": "1    default    active"})
    result, _, fake = run(fake=fake)
    assert result.status == "rolled_back"
    assert "VLAN 10 Sales" in result.error["message"]
    assert ("exec", "configure revert now") in fake.sent


def test_p5_denylisted_custom_command_blocked_nothing_sent():
    result, states, fake = run({**VLAN_PLAN, "custom_commands": ["do rel"]})
    assert result.status == "blocked" and "blocked" in result.error["message"]
    assert fake.config_sent() == [] and not any(k == "config_mode" for k, _ in fake.sent)
    assert "applying" not in states


def test_p6_management_interface_protected():
    plan = {"svis": [{"vlan": 1, "ip": "10.0.0.9/24"}]}  # changes the IP of Vlan1, which holds 10.0.0.2
    result, states, fake = run(plan)
    assert result.status == "blocked" and "management IP" in result.error["message"]
    assert fake.config_sent() == [] and "applying" not in states


def test_p6_no_interface_holds_mgmt_ip_fails_closed():
    result, _, fake = run(mgmt_ip="10.9.9.9")
    assert result.status == "blocked" and fake.config_sent() == []


def test_p9_rollback_refused_needs_manual_action():
    fake = FakeConnection(fail_on={"vlan 10": "% Invalid input detected at '^' marker."},
                          exec_responses={"configure revert now": "% Error: no rollback pending"})
    result, _, _ = run(fake=fake)
    assert result.status == "failed" and any(MANUAL in n for n in result.notes)


def test_p10_auth_failure_not_retried_and_sanitised():
    connector = FakeConnector(fail=ConnectFailed("auth", "Login failed: check the username and password."))
    result, states, _ = run(connector=connector)
    assert result.status == "failed" and connector.opens == 1
    assert result.error["message"].startswith("Login failed") and states == ["connecting"]


def test_connect_timeout_retried_once():
    timeout = ConnectFailed("timeout", "The device did not answer in time.")
    result, _, _ = run(connector=(c := FakeConnector(fail=timeout, fail_times=1)))
    assert result.status == "success" and c.opens == 2 and any("trying once more" in n for n in result.notes)
    result, _, _ = run(connector=(c := FakeConnector(fail=timeout, fail_times=5)))
    assert result.status == "failed" and c.opens == 2  # only one retry


def test_p11_rsa_prompt_answered_only_when_replacing():
    plan = {"basic": {"hostname": "sw1", "domain": "lab.example.net"},
            "ssh": {"username": "netadmin", "password": "Plan-User-Pw-3", "regenerate_keys": True}}
    fake = FakeConnection(responses={"show crypto key mypubkey rsa": RSA_KEYS}, rsa_prompt=True)
    result, _, fake = run(plan, fake)
    assert ("config", "crypto key generate rsa modulus 2048") in fake.sent and ("answer", "yes") in fake.sent
    # Keys exist and the plan does not ask to replace them → the line is not sent at all.
    plan["ssh"]["regenerate_keys"] = False
    _, _, fake2 = run(plan, FakeConnection(responses={"show crypto key mypubkey rsa": RSA_KEYS}, rsa_prompt=True))
    assert not any(c.startswith("crypto key generate") for c in fake2.config_sent())


def test_secrets_scrubbed_from_result():
    plan = {"basic": {"hostname": "sw1", "domain": "lab.example.net"},
            "ssh": {"username": "netadmin", "password": "Plan-User-Pw-3"}}
    fake = FakeConnection(responses={"show running-config": "hostname sw1\narchive\n path flash0:x\n"
                                     "username netadmin privilege 15 secret 9 $9$abc\ninterface Vlan1\n"
                                     " ip address 10.0.0.2 255.255.255.0"},
                          fail_on={"ip ssh version 2": "% Invalid input near Plan-User-Pw-3 Device-Login-Pw-1"})
    result, _, fake = run(plan, fake)
    assert ("config", "username netadmin privilege 15 secret Plan-User-Pw-3") in fake.sent  # the device needs it
    stored = repr(result)
    for secret in ("Plan-User-Pw-3", "Device-Login-Pw-1", "Enable-Login-Pw-2", "$9$abc"):
        assert secret not in stored, secret


def test_cancel_before_apply():
    calls = {"n": 0}

    def cancelled():
        calls["n"] += 1
        return calls["n"] >= 3  # requested while "checking" is about to start

    result, states, fake = run(cancelled=cancelled)
    assert result.status == "cancelled" and fake.config_sent() == []
    assert "applying" not in states
