"""Catalog queries, device validation, RBAC and audit (Phase 1C)."""

import re

import pytest

from app.services.catalog import load_file


def test_catalog_file_is_consistent():
    data = load_file()
    os_ids = {d["_id"] for d in data["os_drivers"]}
    brands = {b["_id"] for b in data["brands"]}
    series = {s["_id"]: s for s in data["series"]}
    for s in series.values():
        assert s["brand_id"] in brands and s["os_id"] in os_ids and s["category"] in data["categories"]
    for m in data["models"]:
        s = series[m["series_id"]]
        assert m["os_id"] == s["os_id"] and m["category"] == s["category"] and m["brand_id"] == s["brand_id"]
        assert m["verified"] is False and m["source"] == "sample"
        for example in m["port_examples"]:
            assert re.fullmatch(m["port_pattern"], example), (m["_id"], example)


def test_catalog_drilldown(client_for):
    c = client_for("viewer")
    brands = c.get("/api/catalog/brands", params={"category": "router"}).json()
    assert {"cisco", "juniper", "mikrotik"} <= {b["id"] for b in brands}
    series = c.get("/api/catalog/series", params={"brand_id": "cisco", "category": "router"}).json()
    assert {s["id"] for s in series} == {"cisco-iosv", "cisco-isr4000"}
    models = c.get("/api/catalog/models", params={"series_id": "cisco-isr4000"}).json()
    assert models["total"] == 2
    detail = c.get("/api/catalog/models/cisco-isr4331").json()
    assert detail["os_driver"]["id"] == "cisco_ios"
    assert "vlans" not in detail["capabilities"] and "ospf" in detail["capabilities"]


def test_catalog_search_escapes_regex(client_for):
    c = client_for("viewer")
    assert c.get("/api/catalog/models", params={"q": "c9300"}).json()["total"] == 2
    assert c.get("/api/catalog/models", params={"q": ".*"}).status_code in (200, 422)
    assert c.get("/api/catalog/models", params={"q": ".*"}).json().get("total", 0) == 0
    assert c.get("/api/catalog/models", params={"q": "$where"}).status_code == 422


def test_catalog_rejects_bad_filters(client_for):
    c = client_for("viewer")
    assert c.get("/api/catalog/series", params={"category": "toaster"}).status_code == 422
    assert c.get("/api/catalog/models/NOT_A_SLUG").status_code == 404


SW = {"name": "core-sw1", "model_id": "cisco-c9300-24t", "mgmt_ip": "10.0.0.2", "location": "Lab rack 1"}


def test_create_and_list_device(client_for, db):
    eng = client_for("engineer")
    r = eng.post("/api/devices", json=SW)
    assert r.status_code == 201, r.text
    dev = r.json()
    assert dev["os_id"] == "cisco_ios" and dev["connection"] == {"method": "ssh", "port": 22,
                                                               "serial_port": None, "baud": None}
    assert dev["category"] == "l3switch" and not dev["production"]
    listed = client_for("viewer").get("/api/devices", params={"q": "core"}).json()
    assert listed["total"] == 1
    assert db.audit_log.find_one({"action": "device.create"})


@pytest.mark.parametrize("field,value", [("password", "secret123"), ("enable_secret", "x"), ("os_id", "juniper_junos")])
def test_device_rejects_unknown_fields_including_passwords(client_for, field, value):
    r = client_for("engineer").post("/api/devices", json={**SW, field: value})
    assert r.status_code == 422


@pytest.mark.parametrize("patch,field", [
    ({"name": "core sw1"}, "name"),
    ({"name": "sw1;reload"}, "name"),
    ({"name": "-bad"}, "name"),
    ({"mgmt_ip": "10.0.0.300"}, "mgmt_ip"),
    ({"mgmt_ip": "0.0.0.0"}, "mgmt_ip"),
    ({"location": "rack#1"}, "location"),
    ({"tags": ["Production"]}, "tags.0"),
    ({"tags": [f"t{i}" for i in range(11)]}, "tags"),
    ({"model_id": "does-not-exist"}, "model_id"),
])
def test_device_validation(client_for, patch, field):
    r = client_for("engineer").post("/api/devices", json={**SW, **patch})
    assert r.status_code == 422, r.text
    assert field in r.json()["error"].get("fields", {}), r.json()


def test_telnet_only_to_lab_addresses(client_for):
    eng = client_for("engineer")
    lab = {**SW, "name": "lab1", "mgmt_ip": "192.168.56.10", "connection": {"method": "telnet_lab", "port": 5001}}
    assert eng.post("/api/devices", json=lab).status_code == 201
    public = {**lab, "name": "lab2", "mgmt_ip": "8.8.8.8"}
    assert eng.post("/api/devices", json=public).status_code == 422


def test_serial_needs_com_port_and_no_ip(client_for):
    eng = client_for("engineer")
    dev = {"name": "new-sw", "model_id": "cisco-iosvl2", "connection": {"method": "serial", "serial_port": "COM3"}}
    r = eng.post("/api/devices", json=dev)
    assert r.status_code == 201 and r.json()["connection"]["baud"] == 9600
    assert eng.post("/api/devices", json={**dev, "name": "x", "connection": {"method": "serial"}}).status_code == 422
    bad = {**dev, "name": "y", "connection": {"method": "serial", "serial_port": "/dev/ttyS0"}}
    assert eng.post("/api/devices", json=bad).status_code == 422


def test_connection_method_must_match_driver(client_for):
    ap = {"name": "ap1", "model_id": "ubiquiti-u6-pro", "mgmt_ip": "10.0.30.5"}
    r = client_for("engineer").post("/api/devices", json=ap)
    assert r.status_code == 422 and "connection.method" in r.json()["error"]["fields"]
    r = client_for("engineer").post("/api/devices", json={**ap, "connection": {"method": "none"}})
    assert r.status_code == 201 and r.json()["support"] == "inventory"


def test_duplicates_rejected(client_for):
    eng = client_for("engineer")
    assert eng.post("/api/devices", json=SW).status_code == 201
    r = eng.post("/api/devices", json={**SW, "name": "CORE-SW1", "mgmt_ip": "10.0.0.3"})
    assert r.status_code == 409 and "name" in r.json()["error"]["fields"]
    r = eng.post("/api/devices", json={**SW, "name": "core-sw2"})
    assert r.status_code == 409 and "mgmt_ip" in r.json()["error"]["fields"]


def test_only_admin_changes_production_tag(client_for):
    eng = client_for("engineer")
    admin = client_for("admin")
    r = eng.post("/api/devices", json={**SW, "tags": ["production"]})
    assert r.status_code == 403
    dev = eng.post("/api/devices", json={**SW, "tags": ["core"]}).json()
    assert eng.patch(f"/api/devices/{dev['id']}", json={"tags": ["core", "production"]}).status_code == 403
    r = admin.patch(f"/api/devices/{dev['id']}", json={"tags": ["core", "production"]})
    assert r.status_code == 200 and r.json()["production"]
    assert eng.patch(f"/api/devices/{dev['id']}", json={"tags": ["core"]}).status_code == 403
    # Engineers can still edit other fields of a production device
    assert eng.patch(f"/api/devices/{dev['id']}", json={"location": "Rack 2"}).status_code == 200


def test_update_revalidates_whole_device(client_for):
    eng = client_for("engineer")
    dev = eng.post("/api/devices", json=SW).json()
    r = eng.patch(f"/api/devices/{dev['id']}", json={"connection": {"method": "telnet_lab"}, "mgmt_ip": "8.8.4.4"})
    assert r.status_code == 422
    r = eng.patch(f"/api/devices/{dev['id']}", json={"mgmt_ip": "10.0.0.20"})
    assert r.status_code == 200 and r.json()["mgmt_ip"] == "10.0.0.20"


def test_delete_requires_admin(client_for, db):
    eng = client_for("engineer")
    dev = eng.post("/api/devices", json=SW).json()
    assert eng.delete(f"/api/devices/{dev['id']}").status_code == 403
    assert client_for("viewer").post("/api/devices", json={**SW, "name": "v1"}).status_code == 403
    assert client_for("admin").delete(f"/api/devices/{dev['id']}").status_code == 200
    assert db.devices.count_documents({}) == 0
    assert db.audit_log.find_one({"action": "device.delete"})


def test_device_documents_never_contain_secrets(client_for, db):
    eng = client_for("engineer")
    eng.post("/api/devices", json=SW)
    doc = db.devices.find_one()
    flat = str(doc).lower()
    assert "password" not in flat and "secret" not in flat
