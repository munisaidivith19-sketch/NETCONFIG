"""Saved templates (T1–T5): CRUD, roles, secrets never stored, input validation."""

PLAN = {"basic": {"hostname": "access-sw", "domain": "lab.example.net"},
        "ssh": {"username": "netadmin", "password": "Template-Pw-77", "set_enable_secret": True},
        "vlans": [{"id": 10, "name": "Sales"}]}


def test_t1_create_list_use(client_for, db):
    eng = client_for("engineer")
    r = eng.post("/api/templates", json={"name": "Access switch", "description": "Sales floor", "plan": PLAN})
    assert r.status_code == 201, r.text
    t = r.json()
    assert "password" not in t["plan"]["ssh"] and t["features"]
    assert "Template-Pw-77" not in str(db.templates.find_one({}))
    viewer = client_for("viewer")
    items = viewer.get("/api/templates").json()["items"]
    assert [i["name"] for i in items] == ["Access switch"]
    assert db.audit_log.find_one({"action": "template.create"})


def test_t2_duplicate_name_case_insensitive(client_for):
    eng = client_for("engineer")
    assert eng.post("/api/templates", json={"name": "Core", "plan": {}}).status_code == 201
    r = eng.post("/api/templates", json={"name": "core", "plan": {}})
    assert r.status_code == 409 and r.json()["error"]["fields"]["name"]


def test_t3_roles(client_for):
    eng = client_for("engineer")
    t = eng.post("/api/templates", json={"name": "Core", "plan": {}}).json()
    viewer = client_for("viewer")
    assert viewer.post("/api/templates", json={"name": "X", "plan": {}}).status_code == 403
    assert viewer.delete(f"/api/templates/{t['id']}").status_code == 403
    admin = client_for("admin")
    r = admin.patch(f"/api/templates/{t['id']}", json={"description": "renamed by admin", "plan": PLAN})
    assert r.status_code == 200 and r.json()["description"] == "renamed by admin"
    assert "password" not in r.json()["plan"]["ssh"]
    assert eng.delete(f"/api/templates/{t['id']}").status_code == 204
    assert eng.delete(f"/api/templates/{t['id']}").status_code == 404


def test_t4_other_engineer_cannot_change(client_for, db):
    eng = client_for("engineer")
    t = eng.post("/api/templates", json={"name": "Core", "plan": {}}).json()
    db.templates.update_one({}, {"$set": {"created_by.id": "someone-else"}})
    assert eng.patch(f"/api/templates/{t['id']}", json={"description": "x"}).status_code == 403
    assert eng.delete(f"/api/templates/{t['id']}").status_code == 403


def test_t5_validation(client_for):
    eng = client_for("engineer")
    for body in ({"name": "bad;name", "plan": {}}, {"name": "", "plan": {}}, {"name": "x" * 61, "plan": {}},
                 {"name": "ok", "plan": {"vlans": [{"id": 1, "name": "x"}], "rogue": 1}},
                 {"name": "ok", "plan": {}, "extra": True}):
        assert eng.post("/api/templates", json=body).status_code == 422, body
