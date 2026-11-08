"""Shared fixtures.

Database tests use the real local MongoDB, database ``netconfig_test`` only (CLAUDE.md 9). It is
dropped before and after the session. If MongoDB is not running these tests are skipped with a
clear reason – and a phase is not done while any of them are skipped.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient

from app import clock
from app.config import Settings
from app.main import create_app
from app.services.users import create_user

TEST_DB = "netconfig_test"
BASE_URL = "http://127.0.0.1:8000"
HEADERS = {"X-Requested-With": "NetConfigStudio", "Origin": BASE_URL}
PASSWORDS = {"admin": "Blue-Harbor-Lamp-71", "engineer": "Quiet-River-Stone-42", "viewer": "Green-Paper-Kite-93",
             "admin2": "Silver-Cloud-Gate-58"}


def make_settings(**overrides) -> Settings:
    values = {"env": "test", "mongo_db": TEST_DB, "port": 8000, "bcrypt_rounds": 12,
              "frontend_dist": "does-not-exist", "_env_file": None}
    values.update(overrides)
    return Settings(**values)


@pytest.fixture(scope="session")
def mongo_client():
    client = MongoClient("mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=1500, tz_aware=True)
    try:
        client.admin.command("ping")
    except Exception:  # noqa: BLE001
        pytest.skip("MongoDB not reachable at 127.0.0.1:27017 – start the MongoDB service")
    client.drop_database(TEST_DB)
    yield client
    client.drop_database(TEST_DB)
    client.close()


@pytest.fixture()
def db(mongo_client):
    database = mongo_client[TEST_DB]
    assert database.name == TEST_DB, "tests must never touch any database except netconfig_test"
    for name in database.list_collection_names():
        database[name].delete_many({})
    return database


class FakeClock:
    def __init__(self):
        self.current = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.current

    def advance(self, **kwargs):
        self.current += timedelta(**kwargs)


@pytest.fixture()
def fake_clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(clock, "now", fake)
    return fake


@pytest.fixture()
def settings():
    return make_settings()


@pytest.fixture()
def app(db, settings):
    return create_app(settings)


@pytest.fixture()
def client(app):
    with TestClient(app, base_url=BASE_URL, headers=HEADERS) as c:
        yield c


@pytest.fixture()
def users(db, settings):
    return {role: create_user(db, settings, role, PASSWORDS[role], "admin" if role == "admin2" else role)
            for role in ("admin", "engineer", "viewer", "admin2")}


def login(client: TestClient, username: str) -> TestClient:
    r = client.post("/api/auth/login", json={"username": username, "password": PASSWORDS[username]})
    assert r.status_code == 200, r.text
    return client


@pytest.fixture()
def client_for(app, users):
    """Factory: client_for("engineer") returns a logged-in client for that user."""
    clients = []

    def make(username: str | None) -> TestClient:
        c = TestClient(app, base_url=BASE_URL, headers=HEADERS)
        c.__enter__()
        clients.append(c)
        if username:
            login(c, username)
        return c

    yield make
    for c in clients:
        c.__exit__(None, None, None)
