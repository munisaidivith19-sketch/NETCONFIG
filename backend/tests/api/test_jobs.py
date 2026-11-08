"""Jobs API: approval flow, credentials only at run, vault cleanup, secrets never stored (P12, P13, P16, P19)."""

import json
import logging
from datetime import timedelta

import pytest
from bson import ObjectId

from app import clock
from app.services.simulator import SimulatedConnector

from ..conftest import make_settings

CREDS = {"username": "netops", "password": "Device-Login-Pw-1", "enable_secret": "Enable-Login-Pw-2"}
PLAN = {
    "basic": {"hostname": "lab-sw1", "domain": "lab.example.net"},
    "ssh": {"username": "netadmin", "set_enable_secret": True},
    "vlans": [{"id": 10, "name": "Sales"}],
    "access": [{"interfaces": ["Gi0/1"], "vlan": 10}],
}
RUN = {**CREDS, "ssh_user_password": "Plan-User-Pw-3", "new_enable_secret": "Plan-Enable-Pw-4"}
SECRETS = ["Device-Login-Pw-1", "Enable-Login-Pw-2", "Plan-User-Pw-3", "Plan-Enable-Pw-4"]


@pytest.fixture()
def settings():
    return make_settings(enable_experimental_drivers=True)


@pytest.fixture()
def runner(app):
    r = app.state.runner
    r.connector = SimulatedConnector()
    return r


def make_device(client, name="lab-sw1", ip="10.0.0.2", tags=()):
    r = client.post("/api/devices", json={"name": name, "model_id": "cisco-iosvl2", "mgmt_ip": ip, "tags": list(tags)})
    assert r.status_code == 201, r.text
    return r.json()


def create_job(client, device, plan=PLAN):
    r = client.post("/api/jobs", json={"device_id": device["id"], "plan": plan})
    assert r.status_code == 201, r.text
    return r.json()


def run_job(client, runner, job, body=RUN):
    r = client.post(f"/api/jobs/{job['id']}/run", json=body)
    assert r.status_code == 202, r.text
    runner.wait(job["id"])
    return client.get(f"/api/jobs/{job['id']}").json()


def test_lab_job_success_end_to_end(client_for, runner, db):
    eng = client_for("engineer")
    job = create_job(eng, make_device(eng))
    assert job["status"] == "ready" and job["approval"]["required"] is False
    assert "username netadmin privilege 15 secret ********" in job["steps"][0]["commands"]
    done = run_job(eng, runner, job)
    step = done["steps"][0]
    assert done["status"] == "success", step["error"]
    assert [t["state"] for t in step["timeline"]] == ["ready", "queued", "connecting", "backing_up", "checking",
                                                       "applying", "verifying", "saving", "success"]
    assert step["checks"] and all(c["ok"] for c in step["checks"] if c["required"])
    assert "configure terminal revert timer 10" in step["output"] and "configure confirm" in step["output"]
    assert step["mgmt_interface"] == "Vlan1"
    actions = [a["action"] for a in db.audit_log.find({"target.id": job["id"]}, sort=[("seq", 1)])]
    assert actions == ["job.create", "job.run", "job.finish"]
    assert len(runner.vault) == 0


def test_p12_secrets_never_stored(client_for, runner, db, caplog):
    caplog.set_level(logging.DEBUG)
    eng = client_for("engineer")
    job = create_job(eng, make_device(eng))
    run_job(eng, runner, job)
    # A failing run as well (wrong password path).
    job2 = create_job(eng, make_device(eng, "lab-sw2", "10.0.0.3"))
    run_job(eng, runner, job2, {**RUN, "password": "wrong"})
    dumped = json.dumps([*db.jobs.find(), *db.audit_log.find(), *db.devices.find()], default=str)
    dumped += caplog.text
    for secret in SECRETS:
        assert secret not in dumped, secret
    # The simulator really received the secrets (otherwise this test would prove nothing).
    sim_config = runner.connector.devices["10.0.0.2"].running_config()
    assert "Plan-User-Pw-3" in sim_config and "Plan-Enable-Pw-4" in sim_config


def test_p13_vault_empty_after_failure(client_for, runner):
    eng = client_for("engineer")
    job = create_job(eng, make_device(eng))
    done = run_job(eng, runner, job, {**RUN, "password": "wrong"})
    assert done["status"] == "failed" and done["steps"][0]["error"]["message"].startswith("Login failed")
    assert len(runner.vault) == 0


def test_credentials_rejected_on_create(client_for):
    eng = client_for("engineer")
    dev = make_device(eng)
    r = eng.post("/api/jobs", json={"device_id": dev["id"], "plan": PLAN, "password": "x"})
    assert r.status_code == 422


def test_missing_plan_secret_keeps_job_ready(client_for, runner):
    eng = client_for("engineer")
    job = create_job(eng, make_device(eng))
    r = eng.post(f"/api/jobs/{job['id']}/run", json=CREDS)
    assert r.status_code == 422 and "ssh_user_password" in r.json()["error"]["fields"]
    assert eng.get(f"/api/jobs/{job['id']}").json()["status"] == "ready" and len(runner.vault) == 0


def test_invalid_plan_rejected_on_create(client_for):
    eng = client_for("engineer")
    dev = make_device(eng)
    r = eng.post("/api/jobs", json={"device_id": dev["id"], "plan": {"vlans": [{"id": 1003, "name": "x"}]}})
    assert r.status_code == 422 and "vlans.0.id" in r.json()["error"]["fields"]


# ------------------------------------------------------------- approval
def production_job(client_for):
    admin = client_for("admin")
    dev = make_device(admin, tags=["production"])
    eng = client_for("engineer")
    return eng, admin, create_job(eng, dev, {"vlans": [{"id": 10, "name": "Sales"}]})


def test_production_needs_second_person(client_for, runner, db):
    eng, admin, job = production_job(client_for)
    assert job["status"] == "awaiting_approval" and job["approval"]["required"]
    r = eng.post(f"/api/jobs/{job['id']}/run", json=CREDS)
    assert r.status_code == 409 and len(runner.vault) == 0  # credentials never accepted while waiting
    assert eng.post(f"/api/jobs/{job['id']}/approve").status_code == 403  # engineers cannot approve
    approved = admin.post(f"/api/jobs/{job['id']}/approve").json()
    assert approved["status"] == "ready" and approved["approval"]["approved_by"]["username"] == "admin"
    done = run_job(eng, runner, approved, CREDS)
    assert done["status"] == "success"
    assert db.audit_log.count_documents({"action": "job.approve", "target.id": job["id"]}) == 1


def test_approver_must_be_a_different_user(client_for):
    admin = client_for("admin")
    dev = make_device(admin, tags=["production"])
    job = create_job(admin, dev, {"vlans": [{"id": 10, "name": "Sales"}]})
    r = admin.post(f"/api/jobs/{job['id']}/approve")
    assert r.status_code == 403 and "Two-person" in r.json()["error"]["message"]
    assert client_for("admin2").post(f"/api/jobs/{job['id']}/approve").json()["status"] == "ready"


def set_deadline(db, job, delta):
    db.jobs.update_one({"_id": ObjectId(job["id"])}, {"$set": {"approval.expires_at": clock.now() + delta}})


def test_expiry(client_for, db):
    eng, admin, job = production_job(client_for)
    set_deadline(db, job, -timedelta(seconds=1))
    r = admin.post(f"/api/jobs/{job['id']}/approve")
    assert r.status_code == 409 and "expired" in r.json()["error"]["message"]
    assert eng.get(f"/api/jobs/{job['id']}").json()["status"] == "expired"


def test_approve_just_before_deadline(client_for, db):
    eng, admin, job = production_job(client_for)
    set_deadline(db, job, timedelta(minutes=1))
    assert admin.post(f"/api/jobs/{job['id']}/approve").json()["status"] == "ready"


def test_reject_and_withdraw(client_for, db):
    eng, admin, job = production_job(client_for)
    rejected = admin.post(f"/api/jobs/{job['id']}/reject", json={"reason": "wrong VLAN"}).json()
    assert rejected["status"] == "cancelled" and rejected["cancel_reason"] == "rejected"
    assert admin.post(f"/api/jobs/{job['id']}/approve").status_code == 409
    dev = make_device(eng, "lab-sw9", "10.0.0.9")
    job2 = create_job(eng, dev, {"vlans": [{"id": 10, "name": "Sales"}]})
    withdrawn = eng.post(f"/api/jobs/{job2['id']}/cancel").json()
    assert withdrawn["status"] == "cancelled" and withdrawn["cancel_reason"] == "withdrawn"
    assert eng.post(f"/api/jobs/{job2['id']}/run", json=CREDS).status_code == 409


def test_production_experimental_driver_needs_flag(app, client_for, settings):
    settings.enable_experimental_drivers = False
    admin = client_for("admin")
    dev = make_device(admin, tags=["production"])
    body = {"device_id": dev["id"], "plan": {"vlans": [{"id": 10, "name": "a"}]}}
    r = client_for("engineer").post("/api/jobs", json=body)
    assert r.status_code == 422 and "ENABLE_EXPERIMENTAL_DRIVERS" in r.json()["error"]["fields"]["device_id"]


def test_approval_binding_detects_changed_commands(client_for, runner, db):
    eng = client_for("engineer")
    job = create_job(eng, make_device(eng), {"vlans": [{"id": 10, "name": "Sales"}]})
    db.jobs.update_one({"_id": ObjectId(job["id"])}, {"$set": {"steps.0.commands_hash": "0" * 64}})
    r = eng.post(f"/api/jobs/{job['id']}/run", json=CREDS)
    assert r.status_code == 409 and len(runner.vault) == 0


def test_only_requester_or_admin_runs(client_for, users, settings, app):
    from app.services.users import create_user
    create_user(app.state.db, settings, "engineer2", "Amber-Field-Road-35", "engineer")
    eng = client_for("engineer")
    job = create_job(eng, make_device(eng), {"vlans": [{"id": 10, "name": "Sales"}]})
    other = client_for(None)
    login = {"username": "engineer2", "password": "Amber-Field-Road-35"}
    assert other.post("/api/auth/login", json=login).status_code == 200
    assert other.post(f"/api/jobs/{job['id']}/run", json=CREDS).status_code == 403


# ------------------------------------------------------------ runner rules
def test_p16_device_busy(client_for, runner, db):
    eng = client_for("engineer")
    dev = make_device(eng)
    job = create_job(eng, dev, {"vlans": [{"id": 10, "name": "Sales"}]})
    db.jobs.insert_one({"status": "applying", "steps": [{"device_id": ObjectId(dev["id"])}], "created_at": clock.now()})
    r = eng.post(f"/api/jobs/{job['id']}/run", json=CREDS)
    assert r.status_code == 409 and "Another job" in r.json()["error"]["message"]


def test_p19_crash_recovery(runner, db):
    _id = db.jobs.insert_one({"status": "applying", "steps": [{"status": "applying", "timeline": []}],
                              "created_at": clock.now()}).inserted_id
    assert runner.recover() == 1
    doc = db.jobs.find_one({"_id": _id})
    assert doc["status"] == "failed" and "Interrupted" in doc["steps"][0]["error"]["message"]


def test_viewer_reads_history_but_cannot_act(client_for, runner):
    eng = client_for("engineer")
    job = create_job(eng, make_device(eng), {"vlans": [{"id": 10, "name": "Sales"}]})
    viewer = client_for("viewer")
    listing = viewer.get("/api/jobs").json()
    assert listing["total"] == 1 and "output" not in listing["items"][0]["steps"][0]
    assert viewer.get(f"/api/jobs/{job['id']}").status_code == 200
    assert viewer.post(f"/api/jobs/{job['id']}/run", json=CREDS).status_code == 403
    assert viewer.get("/api/jobs", params={"status": "nonsense"}).status_code == 422
