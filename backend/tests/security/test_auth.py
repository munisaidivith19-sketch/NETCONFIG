"""Authentication, sessions, lockout, RBAC (TEST_PLAN S9–S15, S20–S21)."""

import pytest
from fastapi import APIRouter
from fastapi.routing import APIRoute

from app.main import ROUTERS
from app.security.rbac import PUBLIC_ROUTES, assert_all_routes_protected, iter_api_routes, route_role
from app.services.audit import verify_chain
from tests.conftest import PASSWORDS

# Every /api route and the minimum role it needs. A new route that is not listed here fails
# test_rbac_table_covers_every_route, so nobody can add an endpoint without deciding its role.
EXPECTED_ROLES = {
    ("GET", "/api/health"): None,
    ("POST", "/api/auth/login"): None,
    ("POST", "/api/auth/logout"): "viewer",
    ("GET", "/api/auth/me"): "viewer",
    ("POST", "/api/auth/password"): "viewer",
    ("GET", "/api/users"): "admin",
    ("POST", "/api/users"): "admin",
    ("PATCH", "/api/users/{user_id}"): "admin",
    ("DELETE", "/api/users/{user_id}"): "admin",
    ("GET", "/api/audit"): "admin",
    ("GET", "/api/audit/verify"): "admin",
}



def test_rbac_table_covers_every_route():
    actual = {(m, p): (None if (m, p) in PUBLIC_ROUTES else route_role(r)) for m, p, r in iter_api_routes(ROUTERS)}
    assert actual == EXPECTED_ROLES


def test_unprotected_route_stops_startup():
    router = APIRouter()

    @router.get("/api/forgot-auth")
    def forgot():
        return {}

    with pytest.raises(RuntimeError, match="forgot-auth"):
        assert_all_routes_protected([router])


def test_nested_router_fails_closed():
    inner, outer = APIRouter(), APIRouter()

    @inner.get("/api/inner")
    def inner_route():
        return {}

    outer.include_router(inner)
    if all(isinstance(r, APIRoute) for r in outer.routes):
        pytest.skip("this FastAPI version flattens nested routers")
    with pytest.raises(RuntimeError):
        assert_all_routes_protected([outer])


def _call(client, method, path):
    path = path.replace("{user_id}", "0" * 24)
    return client.request(method, path, json={} if method in ("POST", "PATCH") else None)


def test_unauthenticated_requests_rejected(client_for):
    anon = client_for(None)
    for (method, path), role in EXPECTED_ROLES.items():
        if role is None:
            continue
        assert _call(anon, method, path).status_code == 401, (method, path)


@pytest.mark.parametrize("who", ["viewer", "engineer"])
def test_lower_roles_get_403(client_for, who):
    c = client_for(who)
    rank = {"viewer": 0, "engineer": 1, "admin": 2}
    for (method, path), role in EXPECTED_ROLES.items():
        if role is None or path == "/api/auth/logout":
            continue
        status = _call(c, method, path).status_code
        if rank[role] > rank[who]:
            assert status == 403, (method, path, status)
        else:
            assert status != 403, (method, path, status)


def test_login_sets_strict_httponly_cookie(client, users):
    r = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORDS["admin"]})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie
    assert "password" not in r.text


def test_session_token_stored_only_as_hash(client, users, db):
    client.post("/api/auth/login", json={"username": "admin", "password": PASSWORDS["admin"]})
    token = client.cookies.get("ncs_session")
    session = db.sessions.find_one()
    assert session["_id"] != token and len(session["_id"]) == 64


def test_logout_invalidates_server_side(client_for, db):
    c = client_for("engineer")
    token = c.cookies.get("ncs_session")
    assert c.post("/api/auth/logout").status_code == 200
    c.cookies.set("ncs_session", token)
    assert c.get("/api/auth/me").status_code == 401
    assert db.sessions.count_documents({}) == 0


def test_unknown_user_and_wrong_password_look_the_same(client, users):
    a = client.post("/api/auth/login", json={"username": "ghost", "password": "Whatever-123456"})
    b = client.post("/api/auth/login", json={"username": "admin", "password": "Wrong-password-1"})
    assert a.status_code == b.status_code == 401
    assert a.json()["error"]["message"] == b.json()["error"]["message"]


def test_lockout_after_five_failures(client, users, fake_clock):
    for _ in range(5):
        client.post("/api/auth/login", json={"username": "viewer", "password": "Wrong-password-1"})
    good = {"username": "viewer", "password": PASSWORDS["viewer"]}
    assert client.post("/api/auth/login", json=good).status_code == 401
    fake_clock.advance(minutes=14, seconds=59)
    assert client.post("/api/auth/login", json=good).status_code == 401
    fake_clock.advance(seconds=2)
    assert client.post("/api/auth/login", json=good).status_code == 200


def test_login_rate_limited(client, users):
    codes = [client.post("/api/auth/login", json={"username": "nobody", "password": "x"}).status_code
             for _ in range(12)]
    assert 429 in codes


def test_idle_timeout(client_for, fake_clock):
    c = client_for("viewer")
    fake_clock.advance(minutes=29)
    assert c.get("/api/auth/me").status_code == 200
    fake_clock.advance(minutes=30, seconds=1)
    assert c.get("/api/auth/me").status_code == 401


def test_absolute_timeout_even_when_active(client_for, fake_clock):
    c = client_for("viewer")
    for _ in range(16):
        fake_clock.advance(minutes=29)
        assert c.get("/api/auth/me").status_code == 200
    fake_clock.advance(minutes=29)
    assert c.get("/api/auth/me").status_code == 401


def test_disabled_user_loses_session(client_for, users):
    viewer = client_for("viewer")
    admin = client_for("admin")
    r = admin.patch(f"/api/users/{users['viewer']['_id']}", json={"disabled": True})
    assert r.status_code == 200
    assert viewer.get("/api/auth/me").status_code == 401


def test_password_policy_enforced(client_for):
    admin = client_for("admin")
    r = admin.post("/api/users", json={"username": "shorty", "password": "short-pw", "role": "viewer"})
    assert r.status_code == 422 and "password" in r.json()["error"]["fields"]
    r = admin.post("/api/users", json={"username": "newbie", "password": "A-good-long-pass-1", "role": "viewer"})
    assert r.status_code == 201


def test_password_hash_is_bcrypt_cost_12(users):
    assert users["admin"]["password_hash"].startswith("$2b$12$")


def test_users_api_never_returns_hashes(client_for):
    r = client_for("admin").get("/api/users")
    assert r.status_code == 200 and "password_hash" not in r.text and "$2b$" not in r.text


def test_last_admin_protected(client_for, users, db):
    admin = client_for("admin")
    db.users.delete_one({"_id": users["admin2"]["_id"]})
    r = admin.patch(f"/api/users/{users['admin']['_id']}", json={"role": "viewer"})
    assert r.status_code == 409
    r = admin.delete(f"/api/users/{users['admin']['_id']}")
    assert r.status_code == 409


def test_change_password_ends_other_sessions(client_for):
    one = client_for("engineer")
    two = client_for("engineer")
    r = one.post("/api/auth/password", json={"current_password": PASSWORDS["engineer"],
                                             "new_password": "A-brand-new-pass-9"})
    assert r.status_code == 200
    assert one.get("/api/auth/me").status_code == 200
    assert two.get("/api/auth/me").status_code == 401


def test_audit_records_logins_and_user_changes(client_for, client, db):
    client.post("/api/auth/login", json={"username": "admin", "password": "Wrong-password-1"})
    admin = client_for("admin")
    admin.post("/api/users", json={"username": "auditme", "password": "A-good-long-pass-1", "role": "viewer"})
    actions = [(e["action"], e["result"]) for e in db.audit_log.find(sort=[("seq", 1)])]
    assert ("auth.login", "denied") in actions
    assert ("auth.login", "ok") in actions
    assert ("user.create", "ok") in actions
    r = admin.get("/api/audit", params={"action": "user"})
    assert r.status_code == 200 and r.json()["total"] >= 1
    assert verify_chain(db) == (True, None)


def test_audit_chain_detects_tampering(client_for, db):
    client_for("admin")
    client_for("viewer")
    first = db.audit_log.find_one({"seq": 1})
    db.audit_log.update_one({"_id": first["_id"]}, {"$set": {"result": "denied"}})
    assert verify_chain(db) == (False, 1)
