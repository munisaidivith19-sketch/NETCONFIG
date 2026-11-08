"""Localhost guard: DNS rebinding, CSRF to localhost, headers (TEST_PLAN S1–S8, S16–S17)."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import BASE_URL, make_settings


def test_wrong_host_rejected_get_and_post(client):
    assert client.get("/api/health", headers={"Host": "evil.com"}).status_code == 400
    assert client.post("/api/auth/login", headers={"Host": "evil.com:8000"}, json={}).status_code == 400


@pytest.mark.parametrize("host", ["127.0.0.1:8000", "localhost:8000"])
def test_local_hosts_allowed(client, host):
    assert client.get("/api/health", headers={"Host": host}).status_code == 200


def test_rebinding_host_without_port_rejected(client):
    assert client.get("/api/health", headers={"Host": "127.0.0.1"}).status_code == 400


def test_cross_origin_post_rejected(client):
    r = client.post("/api/auth/login", headers={"Origin": "https://evil.com"},
                    json={"username": "admin", "password": "x"})
    assert r.status_code == 403


def test_missing_custom_header_rejected(client):
    r = client.post("/api/auth/login", headers={"X-Requested-With": ""}, json={"username": "a", "password": "b"})
    assert r.status_code == 403


def test_cross_site_fetch_metadata_rejected(client):
    r = client.post("/api/auth/login", headers={"Sec-Fetch-Site": "cross-site"},
                    json={"username": "abc", "password": "b"})
    assert r.status_code == 403


def test_simple_request_text_plain_rejected(client):
    r = client.post("/api/auth/login", content=b'{"username":"abc","password":"x"}',
                    headers={"Content-Type": "text/plain"})
    assert r.status_code == 415


def test_preflight_never_answered(client):
    r = client.options("/api/auth/login", headers={"Origin": "https://evil.com",
                                                   "Access-Control-Request-Method": "POST"})
    assert r.status_code == 403
    assert "access-control-allow-origin" not in r.headers


def test_dev_origin_allowed_only_outside_production(db):
    dev = TestClient(create_app(make_settings(env="development")), base_url=BASE_URL)
    r = dev.post("/api/auth/login", headers={"Origin": "http://localhost:5173", "X-Requested-With": "NetConfigStudio"},
                 json={"username": "nobody", "password": "x"})
    assert r.status_code == 401  # reached the endpoint
    prod = TestClient(create_app(make_settings(env="production")), base_url=BASE_URL)
    r = prod.post("/api/auth/login", headers={"Origin": "http://localhost:5173", "X-Requested-With": "NetConfigStudio"},
                  json={"username": "nobody", "password": "x"})
    assert r.status_code == 403


EXPECTED_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
}


@pytest.mark.parametrize("path,host", [("/api/health", "127.0.0.1:8000"), ("/api/nope", "127.0.0.1:8000"),
                                        ("/api/health", "evil.com")])
def test_security_headers_on_every_response(client, path, host):
    r = client.get(path, headers={"Host": host})
    for name, value in EXPECTED_HEADERS.items():
        assert r.headers[name] == value
    csp = r.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert "unsafe-inline" not in csp
    assert r.headers["x-request-id"]


def test_docs_disabled_in_production(db):
    prod = TestClient(create_app(make_settings(env="production")), base_url=BASE_URL)
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert prod.get(path).status_code == 404


def test_oversize_body_rejected(client):
    big = "a" * 1_100_000
    r = client.post("/api/auth/login", content=big, headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_oversize_field_rejected(client):
    r = client.post("/api/auth/login", json={"username": "a" * 500, "password": "x"})
    assert r.status_code == 422
    assert "username" in r.json()["error"]["fields"]


def test_unknown_field_rejected(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "x", "role": "admin"})
    assert r.status_code == 422


def test_mongo_operator_injection_rejected(client):
    r = client.post("/api/auth/login", json={"username": {"$ne": None}, "password": "x"})
    assert r.status_code == 422


def test_errors_have_request_id_and_no_stack_trace(client):
    r = client.post("/api/auth/login", json={"username": "a"})
    body = r.json()
    assert body["error"]["request_id"] == r.headers["x-request-id"]
    assert "Traceback" not in r.text and "File \"" not in r.text


def test_unhandled_exception_is_safe(app, users):
    @app.get("/api/boom")
    def boom():
        raise RuntimeError("secret detail password=hunter2")

    c = TestClient(app, base_url=BASE_URL, raise_server_exceptions=False)
    r = c.get("/api/boom")
    assert r.status_code == 500
    assert "hunter2" not in r.text and "RuntimeError" not in r.text
    assert r.json()["error"]["request_id"]


def test_refuses_non_local_bind_without_allow_remote():
    with pytest.raises(RuntimeError):
        make_settings(host="0.0.0.0").check_bind_address()  # noqa: S104
    make_settings(host="0.0.0.0", allow_remote=True).check_bind_address()  # noqa: S104


def test_frontend_served_with_spa_fallback_and_no_docs_in_production(db, tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><div id=root></div>")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    prod = TestClient(create_app(make_settings(env="production", frontend_dist=tmp_path)), base_url=BASE_URL)
    assert prod.get("/devices").text.startswith("<!doctype html>")
    assert prod.get("/assets/app.js").status_code == 200
    for path in ("/docs", "/redoc", "/openapi.json", "/api/unknown"):
        assert prod.get(path).status_code == 404, path
    assert prod.get("/../backend/.env").status_code in (200, 404)
    assert "MONGO" not in prod.get("/..%2f..%2fbackend%2f.env.example").text
