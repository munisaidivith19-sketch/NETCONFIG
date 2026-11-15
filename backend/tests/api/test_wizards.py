"""Phase 3B: multi-device push, router link wizard, console bootstrap (W1–W14, docs/TEST_PLAN.md section 6)."""

import pytest

from app.services.connection import ConnectFailed
from app.services.simulator import SimulatedConnector

from ..conftest import make_settings
from ..push.fake import FakeConnection

CREDS = {"username": "netops", "password": "Device-Login-Pw-1", "enable_secret": "Enable-Login-Pw-2"}
VLANS = {"vlans": [{"id": 10, "name": "Sales"}, {"id": 20, "name": "Staff"}],
         "access": [{"interfaces": ["Gi1/0/1"], "vlan": 10}]}
LINK = {"a": {"interface": "GigabitEthernet0/1", "router_id": "1.1.1.1"},
        "b": {"interface": "GigabitEthernet0/1", "router_id": "2.2.2.2"},
        "subnet": "10.255.0.0/30", "protocol": "ospf", "ospf_area": 0}
BOOT = {"hostname": "lab-sw9", "domain": "lab.example.net", "admin_username": "netadmin",
        "mgmt": {"vlan": 99, "ip": "10.10.10.2/24", "gateway": "10.10.10.1"}}
BOOT_RUN = {"ssh_user_password": "Admin-User-Pw-5", "new_enable_secret": "New-Enable-Pw-6"}
INVALID = "% Invalid input detected at '^' marker."


@pytest.fixture()
def settings():
    return make_settings(enable_experimental_drivers=True)


class MixedConnector:
    """Simulated devices, except the hosts listed in `fakes` (scripted) or `refuse_ssh` (SSH login fails)."""

    def __init__(self, fakes=None, refuse_ssh=False, ssh_error=None, exec_errors=None):
        self.sim = SimulatedConnector()
        self.fakes = fakes or {}
        self.ssh_error = ssh_error or (ConnectFailed("timeout", "The device did not answer in time.")
                                       if refuse_ssh else None)
        self.exec_errors = exec_errors or {}  # host -> {exec command: device output} on a simulated device
        self.sent: dict[str, list[str]] = {}  # host -> exec commands sent to it
        self.order: list[tuple[str, str]] = []  # (host, exec command) across all devices, in order

    def open(self, params, who=None, notes=None):
        if params.host in self.fakes:
            return self.fakes[params.host]
        if self.ssh_error and params.method == "ssh":
            raise self.ssh_error
        conn = self.sim.open(params, who=who, notes=notes)
        errors, sent = self.exec_errors.get(params.host, {}), self.sent.setdefault(params.host, [])
        real_exec = conn.exec

        def exec_(command, prompts=None):
            sent.append(command)
            self.order.append((params.host, command))
            return errors[command] if command in errors else real_exec(command, prompts)

        conn.exec = exec_
        return conn


@pytest.fixture()
def runner(app):
    r = app.state.runner
    r.connector = MixedConnector()
    return r


def device(client, name, model="cisco-ws-c2960x-24ts-l", ip="10.0.0.2", connection=None, tags=()):
    body = {"name": name, "model_id": model, "mgmt_ip": ip, "tags": list(tags)}
    if connection:
        body["connection"] = connection
    r = client.post("/api/devices", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def run(client, runner, job_id, body):
    r = client.post(f"/api/jobs/{job_id}/run", json=body)
    assert r.status_code == 202, r.text
    runner.wait(job_id)
    return client.get(f"/api/jobs/{job_id}").json()


def link_job(eng, a, b, **over):
    spec = {**LINK, **over, "a": {**LINK["a"], "device_id": a}, "b": {**LINK["b"], "device_id": b}}
    return {"link": spec}


# ------------------------------------------------------------------------- multi
def test_w1_multi_preview_and_push(client_for, runner, db):
    eng = client_for("engineer")
    ids = [device(eng, "sw1", ip="10.0.0.2"), device(eng, "sw2", ip="10.0.0.3")]
    pv = eng.post("/api/jobs/preview", json={"device_ids": ids, "plan": VLANS}).json()
    assert pv["ok"], pv["errors"]
    assert pv["kind"] == "multi" and [s["device_name"] for s in pv["steps"]] == ["sw1", "sw2"]
    assert "vlan 10" in pv["steps"][0]["commands"] and pv["steps"][0]["commands"] == pv["steps"][1]["commands"]
    job = eng.post("/api/jobs", json={"device_ids": ids, "plan": VLANS}).json()
    assert job["kind"] == "multi" and [s["status"] for s in job["steps"]] == ["ready", "ready"]
    done = run(eng, runner, job["id"], CREDS)
    assert done["status"] == "success" and [s["status"] for s in done["steps"]] == ["success", "success"]
    assert done["summary"] == "2 of 2 devices changed: sw1, sw2."
    assert all("configure confirm" in s["output"] for s in done["steps"])
    assert len(runner.vault) == 0


def test_multi_job_custom_commands_audited_per_device(client_for, db):
    # CLAUDE.md 8.5: custom commands are written to the audit log, also when the job is created without
    # /api/plans/preview (several switches use /api/jobs/preview).
    eng = client_for("engineer")
    ids = [device(eng, "sw1", ip="10.0.0.2"), device(eng, "sw2", ip="10.0.0.3")]
    plan = {**VLANS, "custom_commands": ["lldp run"]}
    job = eng.post("/api/jobs", json={"device_ids": ids, "plan": plan})
    assert job.status_code == 201, job.text
    entries = list(db.audit_log.find({"action": "job.custom_commands"}, sort=[("seq", 1)]))
    assert [e["target"]["name"] for e in entries] == ["sw1", "sw2"]
    assert all(e["details"]["commands"] == ["lldp run"] and e["target"]["job"] == job.json()["id"]
               for e in entries)


def test_w2_multi_refuses_per_device_settings_and_non_switches(client_for):
    eng = client_for("engineer")
    ids = [device(eng, "sw1", ip="10.0.0.2"), device(eng, "sw2", ip="10.0.0.3")]
    pv = eng.post("/api/jobs/preview", json={"device_ids": ids, "plan": {
        **VLANS, "basic": {"hostname": "same-name"}}}).json()
    assert not pv["ok"] and "plan.basic" in pv["errors"]
    r1 = device(eng, "r1", model="cisco-iosv", ip="10.0.0.11")
    pv = eng.post("/api/jobs/preview", json={"device_ids": [ids[0], r1], "plan": {"vlans": VLANS["vlans"]}}).json()
    assert not pv["ok"] and "r1 is not a switch" in pv["errors"]["steps.1.device_id"]
    assert eng.post("/api/jobs", json={"device_ids": [ids[0], ids[0]], "plan": VLANS}).status_code == 422
    assert eng.post("/api/jobs", json={"device_ids": [ids[0]], "plan": VLANS}).status_code == 422  # min 2


def test_w3_multi_stops_at_first_failure(client_for, runner):
    eng = client_for("engineer")
    ids = [device(eng, "sw1", ip="10.0.0.2"), device(eng, "sw2", ip="10.0.0.3")]
    job = eng.post("/api/jobs", json={"device_ids": ids, "plan": VLANS}).json()
    bad_login = {**CREDS, "logins": [{"device_id": ids[0], "username": "netops", "password": "wrong"}]}
    done = run(eng, runner, job["id"], bad_login)
    assert [s["status"] for s in done["steps"]] == ["failed", "cancelled"]
    assert "stop on failure" in done["steps"][1]["notes"][0]
    assert done["status"] == "failed" and done["summary"] == "0 of 2 devices changed."


def test_w4_multi_continue_after_failure(client_for, runner):
    eng = client_for("engineer")
    ids = [device(eng, "sw1", ip="10.0.0.2"), device(eng, "sw2", ip="10.0.0.3")]
    job = eng.post("/api/jobs", json={"device_ids": ids, "plan": VLANS, "stop_on_failure": False}).json()
    bad_login = {**CREDS, "logins": [{"device_id": ids[0], "username": "netops", "password": "wrong"}]}
    done = run(eng, runner, job["id"], bad_login)
    assert [s["status"] for s in done["steps"]] == ["failed", "success"]
    assert done["status"] == "failed" and done["summary"] == "1 of 2 devices changed: sw2."


def test_w4b_refused_login_is_not_tried_on_more_switches(client_for, runner):
    """Even with stop_on_failure off: a rejected shared login would lock the TACACS/RADIUS account."""
    eng = client_for("engineer")
    ids = [device(eng, f"sw{n}", ip=f"10.0.0.{n + 1}") for n in (1, 2, 3)]
    job = eng.post("/api/jobs", json={"device_ids": ids, "plan": VLANS, "stop_on_failure": False}).json()
    done = run(eng, runner, job["id"], {**CREDS, "password": "wrong"})
    assert [s["status"] for s in done["steps"]] == ["failed", "cancelled", "cancelled"]
    assert "sw1 refused the login" in done["steps"][2]["notes"][0]


# -------------------------------------------------------------------------- link
def test_w5_link_preview_both_sides_match(client_for):
    eng = client_for("engineer")
    a, b = device(eng, "r1", model="cisco-iosv", ip="10.0.0.11"), device(eng, "r2", model="cisco-iosv", ip="10.0.0.12")
    pv = eng.post("/api/jobs/preview", json=link_job(eng, a, b)).json()
    assert pv["ok"], pv["errors"]
    ca, cb = (s["commands"] for s in pv["steps"])
    assert "interface GigabitEthernet0/1" in ca and " description link to r2" in ca
    assert " ip address 10.255.0.1 255.255.255.252" in ca and " ip address 10.255.0.2 255.255.255.252" in cb
    assert any("router-id 1.1.1.1" in c for c in ca) and any("router-id 2.2.2.2" in c for c in cb)
    assert pv["checks"] and all(c["ok"] for c in pv["checks"])
    assert [s["role"] for s in pv["steps"]] == ["A", "B"]


def test_w6_link_31_and_bgp(client_for):
    eng = client_for("engineer")
    a, b = device(eng, "r1", model="cisco-iosv", ip="10.0.0.11"), device(eng, "r2", model="cisco-iosv", ip="10.0.0.12")
    body = link_job(eng, a, b, subnet="10.255.0.0/31", protocol="bgp")
    body["link"]["a"]["asn"], body["link"]["b"]["asn"] = 65001, 65002
    pv = eng.post("/api/jobs/preview", json=body).json()
    assert pv["ok"], pv["errors"]
    ca, cb = (s["commands"] for s in pv["steps"])
    assert " ip address 10.255.0.0 255.255.255.254" in ca and " ip address 10.255.0.1 255.255.255.254" in cb
    assert " neighbor 10.255.0.1 remote-as 65002" in ca and " neighbor 10.255.0.0 remote-as 65001" in cb


@pytest.mark.parametrize(("change", "field"), [
    ({"subnet": "10.255.0.0/29"}, "link.subnet"),
    ({"subnet": "10.255.0.1/30"}, "link.subnet"),
    ({"b": {"interface": "GigabitEthernet0/1", "router_id": "1.1.1.1"}}, "link.b.router_id"),
    ({"a": {"interface": "GigabitEthernet0/1"}}, "link.a.router_id"),
    ({"protocol": "eigrp"}, "link.eigrp_asn"),
    ({"a": {"interface": "GigabitEthernet9/9", "router_id": "1.1.1.1"}}, "link.a.interface"),
])
def test_w7_link_validation(client_for, change, field):
    eng = client_for("engineer")
    a, b = device(eng, "r1", model="cisco-iosv", ip="10.0.0.11"), device(eng, "r2", model="cisco-iosv", ip="10.0.0.12")
    body = link_job(eng, a, b)
    for side in ("a", "b"):
        if side in change:
            change = {**change, side: {**change[side], "device_id": body["link"][side]["device_id"]}}
    body["link"].update(change)
    pv = eng.post("/api/jobs/preview", json=body).json()
    assert not pv["ok"] and field in pv["errors"], pv["errors"]


def test_w8_link_needs_two_routers(client_for):
    eng = client_for("engineer")
    a, sw = device(eng, "r1", model="cisco-iosv", ip="10.0.0.11"), device(eng, "sw1", ip="10.0.0.2")
    pv = eng.post("/api/jobs/preview", json=link_job(eng, a, a)).json()
    assert "link.b.device_id" in pv["errors"]
    pv = eng.post("/api/jobs/preview", json=link_job(eng, a, sw)).json()
    assert "not a router" in pv["errors"]["link.b.device_id"]


def test_w9_link_success_confirms_both(client_for, runner):
    eng = client_for("engineer")
    a, b = device(eng, "r1", model="cisco-iosv", ip="10.0.0.11"), device(eng, "r2", model="cisco-iosv", ip="10.0.0.12")
    job = eng.post("/api/jobs", json=link_job(eng, a, b)).json()
    assert job["kind"] == "link" and job["link_checks"]
    done = run(eng, runner, job["id"], CREDS)
    assert done["status"] == "success", [s["error"] for s in done["steps"]]
    for s in done["steps"]:
        assert s["status"] == "success" and "configure confirm" in s["output"] and "write memory" in s["output"]


def test_w10_link_b_fails_so_a_is_rolled_back(client_for, runner):
    eng = client_for("engineer")
    a, b = device(eng, "r1", model="cisco-iosv", ip="10.0.0.11"), device(eng, "r2", model="cisco-iosv", ip="10.0.0.2")
    fake_b = FakeConnection(fail_on={" ip address 10.255.0.2 255.255.255.252": INVALID})
    runner.connector = MixedConnector(fakes={"10.0.0.2": fake_b})
    job = eng.post("/api/jobs", json=link_job(eng, a, b)).json()
    done = run(eng, runner, job["id"], CREDS)
    sa, sb = done["steps"]
    assert sb["status"] == "rolled_back" and sb["error"]["command"] == " ip address 10.255.0.2 255.255.255.252"
    assert sa["status"] == "rolled_back" and "configure revert now" in sa["output"]
    assert "configure confirm" not in sa["output"] and "r2 failed" in sa["error"]["message"]
    assert done["status"] == "rolled_back"


def test_w11_link_a_fails_so_b_is_untouched(client_for, runner):
    eng = client_for("engineer")
    a, b = device(eng, "r1", model="cisco-iosv", ip="10.0.0.2"), device(eng, "r2", model="cisco-iosv", ip="10.0.0.12")
    fake_a = FakeConnection(fail_on={" ip address 10.255.0.1 255.255.255.252": INVALID})
    runner.connector = MixedConnector(fakes={"10.0.0.2": fake_a})
    job = eng.post("/api/jobs", json=link_job(eng, a, b)).json()
    done = run(eng, runner, job["id"], CREDS)
    assert [s["status"] for s in done["steps"]] == ["rolled_back", "cancelled"]
    assert done["steps"][1]["output"] == ""


def test_w11b_link_a_not_saved_b_still_confirmed(client_for, runner):
    """A was confirmed (its change is kept), so B must be kept too, even though A's save failed."""
    eng = client_for("engineer")
    a, b = device(eng, "r1", model="cisco-iosv", ip="10.0.0.11"), device(eng, "r2", model="cisco-iosv", ip="10.0.0.12")
    runner.connector = MixedConnector(exec_errors={"10.0.0.11": {"write memory": INVALID}})
    job = eng.post("/api/jobs", json=link_job(eng, a, b)).json()
    done = run(eng, runner, job["id"], CREDS)
    sa, sb = done["steps"]
    assert sb["status"] == "success" and "configure confirm" in sb["output"]
    order = runner.connector.order  # both sides confirmed before either was saved
    assert order.index(("10.0.0.12", "configure confirm")) < order.index(("10.0.0.11", "write memory"))
    assert sa["status"] == "failed" and any("NOT saved" in n for n in sa["notes"])
    assert "configure revert now" not in sa["output"] + sb["output"]


def test_w11c_link_b_not_confirmed_a_needs_manual_action(client_for, runner):
    eng = client_for("engineer")
    a, b = device(eng, "r1", model="cisco-iosv", ip="10.0.0.11"), device(eng, "r2", model="cisco-iosv", ip="10.0.0.12")
    runner.connector = MixedConnector(exec_errors={"10.0.0.12": {"configure confirm": INVALID}})
    job = eng.post("/api/jobs", json=link_job(eng, a, b)).json()
    done = run(eng, runner, job["id"], CREDS)
    sa, sb = done["steps"]
    assert sb["status"] == "rolled_back" and "write memory" not in runner.connector.sent["10.0.0.12"]
    # A was already confirmed (no timer left to undo it), so it is at least NOT saved: its startup config
    # still matches B's, and the job asks for manual action.
    sent_a = runner.connector.sent["10.0.0.11"]
    assert "configure confirm" in sent_a and "write memory" not in sent_a
    assert sa["status"] == "failed" and any("MANUAL ACTION REQUIRED" in n and "r2 was not confirmed" in n
                                            and "NOT saved" in n for n in sa["notes"])
    assert done["status"] != "success"


def test_w11d_link_internal_error_rolls_back_and_records_a(client_for, runner, db, monkeypatch):
    from app.services import jobs

    eng = client_for("engineer")
    a, b = device(eng, "r1", model="cisco-iosv", ip="10.0.0.11"), device(eng, "r2", model="cisco-iosv", ip="10.0.0.12")
    original = jobs.Execution._input

    def broken(self, i):
        if i == 1:
            raise RuntimeError("database gone")
        return original(self, i)

    monkeypatch.setattr(jobs.Execution, "_input", broken)
    job = eng.post("/api/jobs", json=link_job(eng, a, b)).json()
    done = run(eng, runner, job["id"], CREDS)
    sa, sb = done["steps"]
    assert sa["status"] == "rolled_back" and "configure revert now" in sa["output"]
    assert sb["status"] == "failed" and "Internal error (RuntimeError)" in sb["error"]["message"]
    assert db.audit_log.find_one({"action": "job.rollback", "target.id": job["id"]})


def test_w12_link_production_needs_approval(client_for, runner):
    eng = client_for("engineer")
    a = device(eng, "r1", model="cisco-iosv", ip="10.0.0.11")
    b = device(client_for("admin"), "r2", model="cisco-iosv", ip="10.0.0.12", tags=["production"])
    job = eng.post("/api/jobs", json=link_job(eng, a, b)).json()
    assert job["status"] == "awaiting_approval" and {s["status"] for s in job["steps"]} == {"awaiting_approval"}
    admin = client_for("admin")
    ok = admin.post(f"/api/jobs/{job['id']}/approve").json()
    assert ok["status"] == "ready" and {s["status"] for s in ok["steps"]} == {"ready"}


# --------------------------------------------------------------------- bootstrap
CONSOLE = {"method": "telnet_lab", "port": 5000}


def test_w13_bootstrap_over_lab_console_then_ssh(client_for, runner, db):
    eng = client_for("engineer")
    dev = device(eng, "new-sw", ip="127.0.0.1", connection=CONSOLE)
    pv = eng.post("/api/jobs/preview", json={"device_id": dev, "bootstrap": BOOT}).json()
    assert pv["ok"], pv["errors"]
    cmds = pv["steps"][0]["commands"]
    for line in ("hostname lab-sw9", "ip domain name lab.example.net", "interface Vlan99",
                 " ip address 10.10.10.2 255.255.255.0", "ip default-gateway 10.10.10.1", "ip ssh version 2",
                 " transport input ssh"):
        assert line in cmds, line
    assert any(c.startswith("crypto key generate rsa") for c in cmds)
    assert any(c.startswith("username netadmin") and "********" in c for c in cmds)
    job = eng.post("/api/jobs", json={"device_id": dev, "bootstrap": BOOT}).json()
    assert job["kind"] == "bootstrap" and job["bootstrap"]["mgmt_ip"] == "10.10.10.2"
    done = run(eng, runner, job["id"], BOOT_RUN)  # a new console has no login
    step = done["steps"][0]
    assert done["status"] == "success", step["error"]
    assert any(c["name"].startswith("SSH login to 10.10.10.2") and c["ok"] for c in step["checks"])
    stored = db.devices.find_one({"name": "new-sw"})
    assert stored["mgmt_ip"] == "10.10.10.2" and stored["connection"]["method"] == "ssh"
    assert stored["connection"]["port"] == 22
    assert db.audit_log.find_one({"action": "device.update", "details.by": "bootstrap"})
    text = str(db.jobs.find_one({"kind": "bootstrap"}))
    assert "Admin-User-Pw-5" not in text and "New-Enable-Pw-6" not in text


def test_w14_bootstrap_ssh_test_fails_device_stays_on_console(client_for, runner, db):
    runner.connector = MixedConnector(refuse_ssh=True)
    eng = client_for("engineer")
    dev = device(eng, "new-sw", ip="127.0.0.1", connection=CONSOLE)
    job = eng.post("/api/jobs", json={"device_id": dev, "bootstrap": BOOT}).json()
    done = run(eng, runner, job["id"], BOOT_RUN)
    step = done["steps"][0]
    assert done["status"] == "success"
    assert any(not c["ok"] and c["name"].startswith("SSH login") for c in step["checks"])
    assert any("stays on its console" in n for n in step["notes"])
    assert db.devices.find_one({"name": "new-sw"})["connection"]["method"] == "telnet_lab"


def test_w14b_bootstrap_unexpected_ssh_error_is_recorded_not_raised(client_for, runner, db):
    runner.connector = MixedConnector(ssh_error=OSError("socket closed"))
    eng = client_for("engineer")
    dev = device(eng, "new-sw", ip="127.0.0.1", connection=CONSOLE)
    job = eng.post("/api/jobs", json={"device_id": dev, "bootstrap": BOOT}).json()
    done = run(eng, runner, job["id"], BOOT_RUN)
    step = done["steps"][0]
    assert done["status"] == "success" and "configure confirm" in step["output"]  # transcript kept
    assert any(c["detail"] == "Internal error (OSError)." for c in step["checks"])
    assert db.devices.find_one({"name": "new-sw"})["connection"]["method"] == "telnet_lab"
    assert db.audit_log.find_one({"action": "job.finish", "target.id": job["id"]})


def test_w15_bootstrap_rules(client_for):
    eng = client_for("engineer")
    ssh_dev = device(eng, "sw-ssh", ip="10.0.0.2")
    pv = eng.post("/api/jobs/preview", json={"device_id": ssh_dev, "bootstrap": BOOT}).json()
    assert not pv["ok"] and "console" in pv["errors"]["device_id"]
    router = device(eng, "new-r", model="cisco-iosv", ip="127.0.0.2", connection=CONSOLE)
    pv = eng.post("/api/jobs/preview", json={"device_id": router, "bootstrap": BOOT}).json()
    assert "bootstrap.mgmt.interface" in pv["errors"]
    boot = {**BOOT, "mgmt": {"interface": "GigabitEthernet0/0", "ip": "10.10.10.5/24", "gateway": "10.10.10.1"}}
    pv = eng.post("/api/jobs/preview", json={"device_id": router, "bootstrap": boot}).json()
    assert pv["ok"], pv["errors"]
    assert "ip route 0.0.0.0 0.0.0.0 10.10.10.1" in pv["steps"][0]["commands"]
    bad_gw = {**BOOT, "mgmt": {**BOOT["mgmt"], "gateway": "10.20.0.1"}}
    sw = device(eng, "new-sw", ip="127.0.0.3", connection=CONSOLE)
    pv = eng.post("/api/jobs/preview", json={"device_id": sw, "bootstrap": bad_gw}).json()
    assert "bootstrap.mgmt.gateway" in pv["errors"]
    for ip, gw in (("10.10.10.2/24", "300.1.1.1"), ("10.10.10.300/24", "10.10.10.1")):  # regex-valid, not IPv4
        r = eng.post("/api/jobs/preview", json={"device_id": sw, "bootstrap": {**BOOT, "mgmt": {
            **BOOT["mgmt"], "ip": ip, "gateway": gw}}})
        assert r.status_code == 422 or not r.json()["ok"], r.text
    taken = {**BOOT, "mgmt": {**BOOT["mgmt"], "ip": "10.0.0.2/24", "gateway": "10.0.0.1"}}
    pv = eng.post("/api/jobs/preview", json={"device_id": sw, "bootstrap": taken}).json()
    assert "sw-ssh" in pv["errors"]["bootstrap.mgmt.ip"]


def test_w16_bootstrap_needs_admin_secrets(client_for, runner):
    eng = client_for("engineer")
    dev = device(eng, "new-sw", ip="127.0.0.1", connection=CONSOLE)
    job = eng.post("/api/jobs", json={"device_id": dev, "bootstrap": BOOT}).json()
    r = eng.post(f"/api/jobs/{job['id']}/run", json={})
    assert r.status_code == 422 and "ssh_user_password" in r.json()["error"]["fields"]
    assert eng.get(f"/api/jobs/{job['id']}").json()["status"] == "ready"


def test_w17_ssh_device_needs_a_login(client_for, runner):
    eng = client_for("engineer")
    job = eng.post("/api/jobs", json={"device_id": device(eng, "sw1"), "plan": VLANS}).json()
    r = eng.post(f"/api/jobs/{job['id']}/run", json={})
    assert r.status_code == 422 and "username" in r.json()["error"]["fields"]
    assert eng.post(f"/api/jobs/{job['id']}/run", json={"username": "netops"}).status_code == 422  # no password


@pytest.mark.parametrize("body", [
    {},
    {"plan": VLANS},
    {"device_id": "0" * 24},
    {"device_id": "0" * 24, "plan": VLANS, "link": LINK},
    {"device_id": "0" * 24, "device_ids": ["1" * 24, "2" * 24], "plan": VLANS},
])
def test_w18_job_shapes(client_for, body):
    assert client_for("engineer").post("/api/jobs/preview", json=body).status_code == 422


def test_w19_kind_filter(client_for):
    eng = client_for("engineer")
    ids = [device(eng, "sw1", ip="10.0.0.2"), device(eng, "sw2", ip="10.0.0.3")]
    eng.post("/api/jobs", json={"device_ids": ids, "plan": VLANS})
    eng.post("/api/jobs", json={"device_id": ids[0], "plan": VLANS})
    assert eng.get("/api/jobs", params={"kind": "multi"}).json()["total"] == 1
    assert eng.get("/api/jobs", params={"kind": "push"}).json()["total"] == 1
