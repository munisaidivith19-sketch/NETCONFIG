"""POST /api/plans/preview (Phase 2B): validation, masking, production rules, audit."""

import json

URL = "/api/plans/preview"
PLAN = {
    "basic": {"hostname": "core1", "domain": "lab.example.net"},
    "ssh": {"username": "netadmin", "password": "Very-Secret-77"},
    "vlans": [{"id": 10, "name": "Sales"}],
    "access": [{"interfaces": ["gi1/0/1"], "vlan": 10}],
}


def make_device(client, **kw):
    body = {"name": "lab-sw1", "model_id": "cisco-c9300-24t", "mgmt_ip": "10.0.0.2"} | kw
    r = client.post("/api/devices", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_preview_for_model(client_for, db):
    eng = client_for("engineer")
    r = eng.post(URL, json={"model_id": "cisco-c9300-24t", "plan": PLAN})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] and body["errors"] == {}
    assert "interface GigabitEthernet1/0/1" in body["commands"]
    assert "username netadmin privilege 15 secret ********" in body["commands"]
    assert "Very-Secret-77" not in r.text
    assert body["verify_commands"][0] == "show running-config"
    assert body["rollback"] == "revert_timer" and body["save_command"] == "write memory"
    assert body["driver"]["support"] == "experimental" and any("experimental" in w for w in body["warnings"])
    assert len(body["commands_hash"]) == 64
    entry = db.audit_log.find_one({"action": "plan.preview"})
    assert entry["result"] == "ok" and entry["details"]["commands_hash"] == body["commands_hash"]
    assert "Very-Secret-77" not in json.dumps(entry, default=str)


def test_preview_returns_errors_by_path(client_for, db):
    eng = client_for("engineer")
    plan = {"vlans": [{"id": 10, "name": "a"}, {"id": 10, "name": "b"}],
            "access": [{"interfaces": ["Gi1/0/99"], "vlan": 10}]}
    body = eng.post(URL, json={"model_id": "cisco-c9300-24t", "plan": plan}).json()
    assert not body["ok"] and body["commands"] == [] and body["commands_hash"] is None
    assert set(body["errors"]) == {"vlans.1.id", "access.0.interfaces.0"}
    assert db.audit_log.find_one({"action": "plan.preview"})["result"] == "invalid"


def test_schema_errors_are_422_with_fields(client_for):
    eng = client_for("engineer")
    r = eng.post(URL, json={"model_id": "cisco-c9300-24t", "plan": {"basic": {"hostname": "sw1\nreload"}}})
    assert r.status_code == 422
    assert "plan.basic.hostname" in r.json()["error"]["fields"]
    r = eng.post(URL, json={"model_id": "cisco-c9300-24t", "plan": {}, "credentials": {"password": "x"}})
    assert r.status_code == 422


def test_unsupported_feature_listed(client_for):
    eng = client_for("engineer")
    plan = {"routing": {"ospf": {"router_id": "1.1.1.1", "interfaces": [{"interface": "Gi1/0/1"}]}}}
    body = eng.post(URL, json={"model_id": "cisco-ws-c2960x-24ts-l", "plan": plan}).json()
    assert not body["ok"] and body["unsupported"][0]["feature"] == "ospf"
    assert "not supported on" in body["errors"]["routing.ospf"]


def test_inventory_only_model_cannot_be_configured(client_for):
    eng = client_for("engineer")
    body = eng.post(URL, json={"model_id": "tplink-tl-sg1016d", "plan": {}}).json()
    assert not body["ok"] and "cannot configure" in body["errors"]["model_id"]
    body = eng.post(URL, json={"model_id": "arista-ceos-lab", "plan": {}}).json()
    assert "planned" in body["errors"]["model_id"]


def test_unknown_targets_404(client_for):
    eng = client_for("engineer")
    assert eng.post(URL, json={"model_id": "no-such-model", "plan": {}}).status_code == 404
    assert eng.post(URL, json={"device_id": "0" * 24, "plan": {}}).status_code == 404


def test_custom_commands_on_lab_device(client_for, db):
    eng = client_for("engineer")
    dev = make_device(eng)
    r = eng.post(URL, json={"device_id": dev["id"], "plan": {"custom_commands": ["cdp run", "lldp run"]}})
    body = r.json()
    assert body["ok"] and body["commands"][-2:] == ["cdp run", "lldp run"]
    entry = db.audit_log.find_one({"action": "plan.custom_commands"})
    assert entry["details"]["commands"] == ["cdp run", "lldp run"] and len(entry["details"]["hash"]) == 64
    assert entry["target"]["id"] == dev["id"]


def test_custom_commands_denylist(client_for, db):
    eng = client_for("engineer")
    dev = make_device(eng)
    body = eng.post(URL, json={"device_id": dev["id"], "plan": {"custom_commands": ["cdp run", "do rel"]}}).json()
    assert not body["ok"] and "blocked" in body["errors"]["custom_commands.1"]
    assert db.audit_log.find_one({"action": "plan.custom_commands"}) is None


def test_custom_commands_vty_protection_over_ssh(client_for):
    eng = client_for("engineer")
    dev = make_device(eng)
    plan = {"custom_commands": ["line vty 0 4", "transport input telnet"]}
    body = eng.post(URL, json={"device_id": dev["id"], "plan": plan}).json()
    assert "custom_commands.1" in body["errors"]


def test_custom_commands_rejected_on_production(client_for):
    admin = client_for("admin")
    dev = make_device(admin, tags=["production"])
    body = admin.post(URL, json={"device_id": dev["id"], "plan": {"custom_commands": ["cdp run"]}}).json()
    assert body["errors"]["custom_commands"] == "custom commands are not allowed on production devices"
    body = admin.post(URL, json={"device_id": dev["id"], "plan": {"vlans": [{"id": 10, "name": "a"}]}}).json()
    assert body["ok"] and body["production"] is True


def test_viewer_cannot_preview(client_for):
    assert client_for("viewer").post(URL, json={"model_id": "cisco-iosv", "plan": {}}).status_code == 403
