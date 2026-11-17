"""Phase 4A: the push engine follows each driver's Session (Junos commit confirmed, EOS session + commit timer,
AOS-CX checkpoint auto) with a fake device session. Nothing vendor-specific lives in the engine."""

import pytest
from pydantic import SecretStr

from app import clock
from app.drivers.arista_eos import AristaEos
from app.drivers.aruba_aoscx import ArubaAoscx
from app.drivers.base import ModelInfo
from app.drivers.experimental.huawei_vrp import HuaweiVrp
from app.drivers.experimental.mikrotik_routeros import MikrotikRouteros
from app.drivers.juniper_junos import JuniperJunos
from app.models.plan import ConfigPlan
from app.services.catalog import load_file
from app.services.connection import ConnectParams
from app.services.push import MANUAL, PushEngine, StepInput

from .fake import FakeConnection, FakeConnector

MODELS = {m["_id"]: m for m in load_file()["models"]}
PASSWORD = SecretStr("Device-Login-Pw-1")
PLAN = {"vlans": [{"id": 10, "name": "Sales"}], "revert_minutes": 10}
JUNOS_SET = "set vlans Sales vlan-id 10"
EOS_RUN = "! Command: show running-config\nhostname sw1\n!\nvlan 10\n   name Sales\n!\nend"
EOS_VLAN = ("VLAN  Name                             Status    Ports\n----- -------- --------- ----\n"
            "1     default     active\n10    Sales       active\n")
CX_RUN = "Current configuration:\n!\n!Version AOS-CX Virtual.10.13\nhostname sw1\nvlan 1\nvlan 10\n    name Sales\n"
CX_VLAN = ("VLAN  Name      Status  Reason  Type    Interfaces\n1     DEFAULT_VLAN_1  up  ok  default  1/1/1\n"
           "10    Sales     up      ok      static\n")


@pytest.fixture(autouse=True)
def fixed_time(monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setattr(clock, "now", lambda: datetime(2026, 11, 11, 10, 0, 0, tzinfo=timezone.utc))  # noqa: UP017


def driver(cls, model_id):
    return cls(ModelInfo.from_doc(MODELS[model_id]))


def run(drv, responses, plan=PLAN, **fake_kw):
    fake = FakeConnection(responses=responses, **fake_kw)
    connector = FakeConnector(fake)
    states = []
    engine = PushEngine(open_connection=lambda p, notes: connector.open(p, notes=notes), on_state=states.append,
                        sleep=lambda s: None)
    params = ConnectParams(method="ssh", device_type=drv.netmiko_device_type, host="10.0.0.2", port=22,
                           username="netops", password=PASSWORD)
    result = engine.run(StepInput(driver=drv, plan=ConfigPlan.model_validate(plan), params=params, mgmt_ip=None,
                                  secrets=[PASSWORD]))
    return result, states, fake


# ------------------------------------------------------------------ Junos
JUNOS = driver(JuniperJunos, "juniper-vjunos-switch")


def test_junos_commit_confirmed_then_confirm_no_save():
    result, states, fake = run(JUNOS, {"show configuration | display set": JUNOS_SET})
    assert result.status == "success", (result.error, result.notes)
    assert fake.sent == [
        ("show", "show configuration | display set"),
        ("config_mode", "configure private"),
        ("config", JUNOS_SET),
        ("config", "commit check"),
        ("config", "commit confirmed 10"),
        ("exit_config", ""),
        ("show", "show configuration | display set"),
        ("config_mode", "configure private"), ("config", "commit"), ("exit_config", ""),
    ]
    assert "saving" not in states  # a Junos commit is already saved


def test_junos_refused_line_is_discarded_nothing_applied():
    result, _, fake = run(JUNOS, {}, fail_on={JUNOS_SET: "syntax error, expecting <statement>."})
    assert result.status == "failed" and result.error["command"] == JUNOS_SET
    assert ("config", "rollback 0") in fake.sent and not any(c.startswith("commit") for c in fake.config_sent())
    assert any("Nothing was applied" in n for n in result.notes)


def test_junos_failed_commit_check_is_discarded():
    result, _, fake = run(JUNOS, {}, fail_on={"commit check": "error: configuration check-out failed"})
    assert result.status == "failed" and result.error["command"] == "commit check"
    assert "commit confirmed 10" not in fake.config_sent() and ("config", "rollback 0") in fake.sent


def test_junos_connection_lost_during_commit_check_never_rolls_back_an_older_commit():
    """Phase 4D review: "commit check" commits nothing. Losing the session there must not send "rollback 1"
    (that would undo the previous, unrelated commit on the device)."""
    class DropsOnCheck(FakeConnection):
        def config_line(self, command, prompts=None):
            if command == "commit check":
                self.gone = True
            return super().config_line(command, prompts)

    fake = DropsOnCheck(responses={"show configuration | display set": JUNOS_SET})
    connector = FakeConnector(fake)
    engine = PushEngine(open_connection=lambda p, notes: connector.open(p, notes=notes), on_state=lambda s: None,
                        sleep=lambda s: None)
    params = ConnectParams(method="ssh", device_type=JUNOS.netmiko_device_type, host="10.0.0.2", port=22,
                           username="netops", password=PASSWORD)
    result = engine.run(StepInput(driver=JUNOS, plan=ConfigPlan.model_validate(PLAN), params=params, mgmt_ip=None,
                                  secrets=[PASSWORD]))
    assert result.status == "failed" and "before anything was applied" in result.error["message"]
    assert "rollback 1" not in fake.config_sent() and connector.opens == 1


def test_junos_failed_verification_rolls_back_the_confirmed_commit():
    result, states, fake = run(JUNOS, {"show configuration | display set": "set system host-name x"})
    assert result.status == "rolled_back" and "rolling_back" in states
    assert fake.sent[-4:] == [("config_mode", "configure private"), ("config", "rollback 1"), ("config", "commit"),
                              ("exit_config", "")]


# -------------------------------------------------------------------- EOS
EOS = driver(AristaEos, "arista-ceos-lab")
SESSION = "ncs-20261111-100000"


def test_eos_session_with_commit_timer_then_commit_and_save():
    result, _, fake = run(EOS, {"show running-config": EOS_RUN, "show vlan": EOS_VLAN})
    assert result.status == "success", (result.error, result.checks)
    assert fake.sent == [
        ("show", "show running-config"),
        ("config_mode", f"configure session {SESSION}"),
        ("config", "vlan 10"), ("config", "   name Sales"),
        ("config", "commit timer 00:10:00"),
        ("exit_config", ""),
        ("show", "show running-config"), ("show", "show vlan"),
        ("exec", f"configure session {SESSION} commit"),
        ("exec", "copy running-config startup-config"),
    ]


def test_eos_refused_line_aborts_the_session():
    result, _, fake = run(EOS, {}, fail_on={"   name Sales": "% Invalid input"})
    assert result.status == "failed" and ("config", "abort") in fake.sent
    assert not any(c.startswith("commit") for c in fake.config_sent())


def test_eos_failed_verification_aborts_the_timed_commit():
    result, _, fake = run(EOS, {"show running-config": "hostname sw1\nend", "show vlan": ""})
    assert result.status == "rolled_back"
    assert ("exec", f"configure session {SESSION} abort") in fake.sent


# ----------------------------------------------------------------- AOS-CX
CX = driver(ArubaAoscx, "aruba-cx-simulator")


def test_aoscx_checkpoint_auto_then_confirm_and_save():
    result, _, fake = run(CX, {"show running-config": CX_RUN, "show vlan": CX_VLAN})
    assert result.status == "success", (result.error, result.checks)
    assert fake.sent == [
        ("show", "show running-config"),
        ("exec", "checkpoint auto 10"),
        ("config_mode", "configure terminal"),
        ("config", "vlan 10"), ("config", "    name Sales"),
        ("config", "end"), ("exit_config", ""),
        ("show", "show running-config"), ("show", "show vlan"),
        ("exec", "checkpoint auto confirm"),
        ("exec", "write memory"),
    ]


def test_aoscx_error_is_undone_by_the_switch_timer():
    result, _, fake = run(CX, {}, fail_on={"    name Sales": "Invalid input: Sales"})
    assert result.status == "rolled_back"
    assert any("restores its previous configuration by itself at 10:10:00 UTC" in n for n in result.notes)
    assert ("config", "end") in fake.sent and ("exec", "checkpoint auto confirm") not in fake.sent
    assert not any(MANUAL in n for n in result.notes)


def test_aoscx_refused_checkpoint_sends_nothing_else():
    result, _, fake = run(CX, {}, exec_responses={"checkpoint auto 10": "% Command incomplete."})
    assert result.status == "failed" and result.error["command"] == "checkpoint auto 10"
    assert not fake.config_sent()


# ---------------------------------------------- experimental (no rollback timer)
HW = driver(HuaweiVrp, "huawei-s5735-l24t4s-a")
HW_RUN = "#\nsysname sw1\n#\nvlan 10\n name Sales\n#\nreturn"


def test_huawei_applies_verifies_and_answers_the_save_question():
    result, states, fake = run(HW, {"display current-configuration": HW_RUN})
    assert result.status == "success", (result.error, result.checks)
    assert fake.sent == [
        ("show", "display current-configuration"),
        ("config_mode", "system-view"),
        ("config", "vlan 10"), ("config", " name Sales"), ("config", " quit"),
        ("exit_config", ""),
        ("show", "display current-configuration"),
        ("exec", "save"),
    ]
    assert fake.answered == ["y"] and "saving" in states
    assert any("no automatic rollback" in n for n in result.notes)


def test_refused_line_without_rollback_timer_needs_manual_action():
    result, _, fake = run(HW, {}, fail_on={" name Sales": "Error: Wrong parameter found at '^' position."})
    assert result.status == "failed" and result.error["command"] == " name Sales"
    assert any(MANUAL in n for n in result.notes) and ("exec", "save") not in fake.sent


def test_failed_verification_without_rollback_timer_is_not_saved():
    result, _, fake = run(HW, {"display current-configuration": "#\nsysname sw1\n#\nreturn"})
    assert result.status == "failed" and any(MANUAL in n for n in result.notes)
    assert ("exec", "save") not in fake.sent


def test_mikrotik_has_no_config_mode_command_and_no_save():
    mt = driver(MikrotikRouteros, "mikrotik-crs326-24g-2s")
    responses = {"/system identity print": "  name: sw2"}
    result, states, fake = run(mt, responses, plan={"basic": {"hostname": "sw2"}, "hardening": {
        "password_encryption": False, "disable_http": False, "login_block": None}})
    assert result.status == "success", (result.error, result.checks)
    assert ("config_mode", "") in fake.sent and ("config", "/system identity set name=sw2") in fake.sent
    assert "saving" not in states and not any(k == "exec" for k, _ in fake.sent)
