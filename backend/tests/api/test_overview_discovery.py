"""Phase 4B: status polling, read-only discovery (facts, OS/model detection, neighbours, VLANs) and the Overview."""

from datetime import timedelta

import pytest

from app import clock
from app.services import status
from app.services.connection import ConnectFailed

PASSWORD = "Dev1ce-Login-Secret"
VERSION = """Cisco IOS Software, vios_l2 Software (vios_l2-ADVENTERPRISEK9-M), Version 15.2(20200924:215240)
sw1 uptime is 2 hours, 3 minutes
cisco IOSvL2 (revision 1.0) processor with 1048576K bytes of memory.
Processor board ID 9ABCDEF0123
"""
VLANS = """VLAN Name                             Status    Ports
---- -------------------------------- --------- -------------------------------
1    default                          active    Gi0/3
10   Staff                            active    Gi0/1
20   Guests                           active
"""
CDP = """-------------------------
Device ID: sw2.lab.example.net
Entry address(es):
  IP address: 10.0.0.3
Platform: Cisco ,  Capabilities: Switch IGMP
Interface: GigabitEthernet0/1,  Port ID (outgoing port): GigabitEthernet0/2
-------------------------
Device ID: core-rtr9
Entry address(es):
  IP address: 10.0.0.254
Interface: GigabitEthernet0/0,  Port ID (outgoing port): GigabitEthernet1/0/48
"""


class FakeConn:
    def __init__(self, outputs):
        self.outputs = outputs
        self.sent = []
        self.closed = False

    def show(self, command):
        self.sent.append(command)
        return self.outputs.get(command, "")

    def close(self):
        self.closed = True


class FakeConnector:
    def __init__(self, outputs=None, fail=None):
        self.conn = FakeConn(outputs or {})
        self.fail = fail
        self.params = None

    def open(self, params, who=None, notes=None):
        self.params = params
        if self.fail:
            raise self.fail
        notes.append("First connection: host key SHA256:abc stored.")
        return self.conn


def add(client, name, model_id="cisco-iosvl2", ip="10.0.0.2", **extra):
    body = {"name": name, "model_id": model_id, "mgmt_ip": ip, "connection": {"method": "ssh"}, **extra}
    r = client.post("/api/devices", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def use(app, connector):
    app.state.runner.connector = connector
    return connector


LOGIN = {"username": "netadmin", "password": PASSWORD}


# ---------------------------------------------------------------- status polling
def test_check_uses_the_port_and_falls_back_to_ping():
    ssh = {"mgmt_ip": "10.0.0.2", "connection": {"method": "ssh", "port": 2222}}
    seen = []
    up = status.check(ssh, pinger=lambda h: 3.0, prober=lambda h, p: seen.append(p) or True)
    assert up["reachable"] is True and up["latency_ms"] == 3.0 and seen == [2222]
    down = status.check(ssh, pinger=lambda h: 3.0, prober=lambda h, p: False)
    assert down["reachable"] is False and down["ping"] is True  # answers ping, but SSH is closed
    camera = {"mgmt_ip": "10.0.5.20", "connection": {"method": "none"}}
    assert status.check(camera, pinger=lambda h: None, prober=lambda h, p: True)["reachable"] is False
    assert status.check(camera, pinger=lambda h: 1.0, prober=lambda h, p: pytest.fail("no port"))["reachable"]


@pytest.mark.parametrize("host", ["10.0.0.1 & calc", "-n 99 10.0.0.1", "example.com", "10.0.0.1\nwhoami"])
def test_ping_accepts_only_an_ip_address(host):
    with pytest.raises(ValueError):
        status.ping(host)


def test_poll_once_stores_status_and_a_sample(client_for, db):
    eng = client_for("engineer")
    a, b = add(eng, "sw1"), add(eng, "sw2", ip="10.0.0.3")
    add(eng, "cam1", "axis-p3245-v", ip=None, connection={"method": "none"})
    sample = status.poll_once(db, pinger=lambda h: 1.0, prober=lambda h, p: h == "10.0.0.2")
    assert sample["up"] == 1 and sample["down"] == 1 and sample["unknown"] == 1
    assert eng.get(f"/api/devices/{a['id']}").json()["status"]["reachable"] is True
    assert eng.get(f"/api/devices/{b['id']}").json()["status"]["reachable"] is False
    assert db.status_samples.count_documents({}) == 1


def test_refresh_needs_an_engineer_and_a_running_poller(client_for):
    assert client_for("viewer").post("/api/overview/refresh").status_code == 403
    r = client_for("engineer").post("/api/overview/refresh")  # tests run with STATUS_POLL_SECONDS=0
    assert r.status_code == 409 and "turned off" in r.json()["error"]["message"]


# ---------------------------------------------------------------- discovery
def test_discovery_stores_parsed_facts_and_never_the_login(app, client_for, db):
    eng = client_for("engineer")
    dev = add(eng, "sw1")
    fake = use(app, FakeConnector({"show version": VERSION, "show vlan brief": VLANS,
                                   "show cdp neighbors detail": CDP}))
    r = eng.post(f"/api/devices/{dev['id']}/discover", json=LOGIN)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["facts"]["model"] == "IOSvL2" and out["facts"]["serial"] == "9ABCDEF0123"
    assert out["facts"]["match"]["status"] == "match"
    assert out["vlans"] == [{"id": 1, "name": "default"}, {"id": 10, "name": "Staff"}, {"id": 20, "name": "Guests"}]
    assert {(n["local"], n["remote"], n["port"]) for n in out["neighbors"]} == {
        ("GigabitEthernet0/1", "sw2.lab.example.net", "GigabitEthernet0/2"),
        ("GigabitEthernet0/0", "core-rtr9", "GigabitEthernet1/0/48")}
    assert out["status"]["reachable"] is True
    # Only read-only commands were sent, the session was closed and the login was dropped.
    assert all(c.startswith("show ") for c in fake.conn.sent) and fake.conn.closed
    assert fake.params.password is None
    assert PASSWORD not in str(db.devices.find_one({"name": "sw1"}))
    assert PASSWORD not in str(list(db.audit_log.find({})))
    entry = db.audit_log.find_one({"action": "device.discover"})
    assert entry["result"] == "ok" and entry["details"]["neighbors"] == 2


def test_discovery_warns_when_the_os_does_not_match(app, client_for):
    eng = client_for("engineer")
    dev = add(eng, "sw1")
    use(app, FakeConnector({"show version": "Arista DCS-7050TX-64\nSoftware image version: 4.30.1F\n"}))
    match = eng.post(f"/api/devices/{dev['id']}/discover", json=LOGIN).json()["facts"]["match"]
    assert match["status"] == "mismatch" and match["detected_os"] == "arista_eos"
    assert "commands would be wrong" in match["message"]


def test_discovery_warns_when_the_model_differs(app, client_for):
    eng = client_for("engineer")
    dev = add(eng, "sw1")
    other = VERSION.replace("cisco IOSvL2 (revision 1.0)", "cisco WS-C2960X-48FPD-L (APM86XXX)")
    use(app, FakeConnector({"show version": other}))
    match = eng.post(f"/api/devices/{dev['id']}/discover", json=LOGIN).json()["facts"]["match"]
    assert match["status"] == "mismatch" and match["detected_model"] == "WS-C2960X-48FPD-L"


def test_discovery_errors_are_safe_and_audited(app, client_for, db):
    eng = client_for("engineer")
    dev = add(eng, "sw1")
    use(app, FakeConnector(fail=ConnectFailed("auth", "Login failed: check the username and password (not retried).")))
    r = eng.post(f"/api/devices/{dev['id']}/discover", json=LOGIN)
    assert r.status_code == 502 and "Login failed" in r.json()["error"]["message"]
    assert db.audit_log.find_one({"action": "device.discover"})["result"] == "failed"
    cam = add(eng, "cam1", "axis-p3245-v", ip="10.0.5.20", connection={"method": "none"})
    assert eng.post(f"/api/devices/{cam['id']}/discover", json=LOGIN).status_code == 422


def test_discovery_rules(app, client_for):
    eng, viewer = client_for("engineer"), client_for("viewer")
    dev = add(eng, "sw1")
    use(app, FakeConnector({"show version": VERSION}))
    assert viewer.post(f"/api/devices/{dev['id']}/discover", json=LOGIN).status_code == 403
    assert eng.post(f"/api/devices/{dev['id']}/discover", json={**LOGIN, "extra": 1}).status_code == 422
    assert eng.post(f"/api/devices/{dev['id']}/discover", json={**LOGIN, "username": "a;reload"}).status_code == 422
    lock = app.state.runner.device_locks[dev["id"]]
    lock.acquire()
    try:  # never read a device while a push is running on it
        assert eng.post(f"/api/devices/{dev['id']}/discover", json=LOGIN).status_code == 409
    finally:
        lock.release()


# ---------------------------------------------------------------- overview
def test_overview_kpis_charts_and_topology(app, client_for, db):
    eng, viewer = client_for("engineer"), client_for("viewer")
    sw1, sw2 = add(eng, "sw1"), add(eng, "sw2", ip="10.0.0.3")
    add(eng, "ap1", "cisco-c9120axi", ip=None, connection={"method": "none"},
        uplink={"device_id": sw2["id"], "interface": "GigabitEthernet0/3"})
    use(app, FakeConnector({"show version": VERSION, "show cdp neighbors detail": CDP}))
    assert eng.post(f"/api/devices/{sw1['id']}/discover", json=LOGIN).status_code == 200
    now = clock.now()
    db.jobs.insert_many([{"status": "success", "kind": "single", "created_at": now, "steps": []},
                         {"status": "rolled_back", "kind": "single", "created_at": now - timedelta(days=1),
                          "steps": []},
                         {"status": "awaiting_approval", "kind": "single", "created_at": now, "steps": []}])

    r = viewer.get("/api/overview")
    assert r.status_code == 200, r.text
    o = r.json()
    k = o["kpis"]
    assert k["devices"] == 3 and k["up"] == 1 and k["unknown"] == 2
    assert k["jobs_7d"] == 3 and k["success_7d"] == 1 and k["failed_7d"] == 1 and k["success_rate_7d"] == 50
    assert k["waiting"] == 1
    assert len(o["jobs_by_day"]) == 14 and sum(d["success"] + d["failed"] for d in o["jobs_by_day"]) == 2
    assert o["devices_by_category"] == {"l3switch": 2, "ap": 1}
    names = {n["id"]: n["name"] for n in o["topology"]["nodes"]}
    pairs = {(names[link["a"]], names[link["b"]], link["source"]) for link in o["topology"]["links"]}
    assert ("sw1", "sw2", "cdp") in pairs or ("sw2", "sw1", "cdp") in pairs  # sw2.lab.example.net = sw2
    assert ("sw2", "ap1", "uplink") in pairs
    external = [n for n in o["topology"]["nodes"] if n["external"]]
    assert [n["name"] for n in external] == ["core-rtr9"]


def test_overview_needs_a_login(client):
    assert client.get("/api/overview").status_code == 401


def test_status_history_spans_the_whole_day(db):
    """Phase 4D review: 150 samples must not be cut to the newest 96; the oldest sample stays in."""
    from app.api.overview import MAX_SAMPLES, _status_history
    now = clock.now()
    db.status_samples.insert_many([{"at": now - timedelta(minutes=150 - i), "up": i} for i in range(150)])
    rows = _status_history(db, now)
    assert len(rows) <= MAX_SAMPLES and rows[0]["up"] == 0


def test_topology_draws_an_uplink_once_and_keeps_unnamed_neighbours_apart():
    from app.api.overview import _topology
    models = {"sw": {"category": "switch"}, "ap": {"category": "ap"}}
    devices = [
        {"_id": "s1", "name": "sw1", "model_id": "sw", "neighbors": [
            {"remote": "ap1", "local": "Gi0/1", "port": "eth0", "protocol": "lldp"},
            {"remote": "unknown", "local": "Gi0/2", "port": None, "protocol": "lldp"}]},
        {"_id": "s2", "name": "sw2", "model_id": "sw", "neighbors": [
            {"remote": "unknown", "local": "Gi0/9", "port": None, "protocol": "lldp"}]},
        {"_id": "a1", "name": "ap1", "model_id": "ap", "uplink": {"device_id": "s1", "interface": "Gi0/1"}},
    ]
    topo = _topology(devices, models)
    between = [link for link in topo["links"] if {link["a"], link["b"]} == {"s1", "a1"}]
    assert len(between) == 1 and between[0]["source"] == "lldp"
    unknown = [n for n in topo["nodes"] if n["external"]]
    assert len(unknown) == 2  # one per device port, not one shared fake node
