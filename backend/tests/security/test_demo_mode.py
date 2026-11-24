"""Public demo mode (DEMO_MODE=true on Render): all-or-nothing settings, one public host, simulated devices only."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.security.clientip import forwarded_ip
from app.services.simulator import SimulatedConnector
from tests.conftest import PASSWORDS, make_settings

DEMO_HOST = "nettool.example.in"
DEMO_URL = f"https://{DEMO_HOST}"
DEMO = {"demo_mode": True, "public_host": DEMO_HOST, "env": "production", "simulate_devices": True,
        "host": "0.0.0.0"}  # noqa: S104 - Render needs the wildcard bind; the Host allowlist still applies


def demo_client(**overrides) -> TestClient:
    return TestClient(create_app(make_settings(**{**DEMO, **overrides})), base_url=DEMO_URL,
                      headers={"X-Requested-With": "NetConfigStudio", "Origin": DEMO_URL})


def test_off_by_default():
    s = make_settings()
    assert not s.demo_mode
    assert DEMO_HOST not in s.allowed_hosts


def test_valid_demo_settings_start_without_certificates():
    s = make_settings(**DEMO)
    s.check_bind_address()  # 0.0.0.0, no ALLOW_REMOTE, no certificate: allowed only because DEMO_MODE holds
    s.check_simulation()
    assert s.allowed_hosts == {DEMO_HOST}
    assert s.allowed_origins == {DEMO_URL}
    assert s.secure_cookies and s.hsts


@pytest.mark.parametrize(("override", "reason"), [
    ({"public_host": ""}, "PUBLIC_HOST"),
    ({"env": "development"}, "ENV must be production"),
    ({"simulate_devices": False}, "SIMULATE_DEVICES"),
    ({"allow_remote": True}, "ALLOW_REMOTE"),
    ({"ai_provider": "groq"}, "AI_PROVIDER"),
])
def test_incomplete_demo_settings_refused(override, reason):
    with pytest.raises(RuntimeError, match=reason):
        make_settings(**{**DEMO, **override}).check_bind_address()


def test_wildcard_bind_still_refused_outside_demo():
    with pytest.raises(RuntimeError):
        make_settings(host="0.0.0.0", env="production").check_bind_address()  # noqa: S104


def test_simulation_in_production_still_refused_outside_demo():
    with pytest.raises(RuntimeError):
        make_settings(env="production", simulate_devices=True).check_simulation()


def test_demo_uses_the_simulator_and_reports_demo(db):
    with demo_client() as c:
        assert isinstance(c.app.state.runner.connector, SimulatedConnector)
        r = c.get("/api/health")
        assert r.status_code == 200 and r.json()["demo"] is True
        assert c.get("/docs").status_code == 404


def test_demo_accepts_only_the_public_host(db):
    with demo_client() as c:
        assert c.get("/api/health", headers={"Host": "127.0.0.1:8000"}).status_code == 400
        assert c.get("/api/health", headers={"Host": "evil.onrender.com"}).status_code == 400
        r = c.post("/api/auth/login", headers={"Origin": "http://localhost:5173"},
                   json={"username": "a", "password": "b"})
        assert r.status_code == 403


def test_demo_cookie_is_secure(db, users):
    with demo_client() as c:
        r = c.post("/api/auth/login", json={"username": "engineer", "password": PASSWORDS["engineer"]})
        assert r.status_code == 200
        cookie = r.headers["set-cookie"].lower()
        assert "secure" in cookie and "httponly" in cookie and "samesite=strict" in cookie
        assert "strict-transport-security" in r.headers


@pytest.mark.parametrize(("peer", "xff", "hops", "expected"), [
    ("10.1.2.3", ["203.0.113.77"], 1, "203.0.113.77"),                # normal: Render wrote the visitor's IP
    ("10.1.2.3", ["1.2.3.4, 203.0.113.77"], 1, "203.0.113.77"),       # spoofed first entry is ignored
    ("10.1.2.3", ["1.2.3.4", "203.0.113.77"], 1, "203.0.113.77"),     # same, as two header lines
    ("10.1.2.3", ["1.2.3.4, 203.0.113.77, 10.9.9.9"], 2, "203.0.113.77"),  # two proxy hops
    ("10.1.2.3", [], 1, "10.1.2.3"),                                  # no header: the peer
    ("10.1.2.3", ["203.0.113.77"], 2, "10.1.2.3"),                    # fewer entries than hops: the peer
    ("10.1.2.3", ["1.2.3.4, not-an-ip"], 1, "10.1.2.3"),              # garbage: the peer
    ("8.8.8.8", ["1.2.3.4"], 1, "8.8.8.8"),                           # public peer = not via the proxy
])
def test_forwarded_ip(peer, xff, hops, expected):
    assert forwarded_ip(peer, xff, hops) == expected


def test_uvicorn_proxy_headers_stay_off():
    import inspect

    import app.__main__ as entry
    assert "proxy_headers=False" in inspect.getsource(entry.main)


def test_request_info_is_admin_only_and_ignores_header_locally(client_for):
    viewer = client_for("viewer")
    assert viewer.get("/api/health/request-info").status_code == 403
    admin = client_for("admin")
    r = admin.get("/api/health/request-info", headers={"X-Forwarded-For": "1.2.3.4"})
    assert r.status_code == 200
    assert r.json()["client_ip"] != "1.2.3.4"  # outside demo mode the header is never believed


def test_demo_blocks_camera_reads(db, users):
    with demo_client() as c:
        c.post("/api/auth/login", json={"username": "engineer", "password": PASSWORDS["engineer"]})
        r = c.post("/api/devices/000000000000000000000000/onvif",
                   json={"username": "u", "password": "p", "port": 80})
        assert r.status_code == 403
        assert "demo" in r.json()["error"]["message"].lower()
