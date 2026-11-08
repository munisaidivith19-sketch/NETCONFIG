"""P14 host-key pinning and P15 Telnet rules, through the real Connector with a fake probe and opener."""

import base64

import pytest
from pydantic import SecretStr

from app.services.connection import ConnectFailed, ConnectParams, HostKey
from app.services.hostkeys import Connector

KEY_A = HostKey("ssh-ed25519", base64.b64encode(b"A" * 51).decode())
KEY_B = HostKey("ssh-ed25519", base64.b64encode(b"B" * 51).decode())


def params(method="ssh", host="10.0.0.2", port=22):
    return ConnectParams(method=method, device_type="cisco_ios", host=host, port=port, username="u",
                         password=SecretStr("Device-Login-Pw-1"))


class Opener:
    def __init__(self):
        self.calls = []

    def __call__(self, p):
        self.calls.append(p)
        return object()


def test_p14_pin_on_first_use_refuse_on_change_then_accept(db, client_for):
    offered = {"key": KEY_A}
    opener = Opener()
    conn = Connector(db, probe=lambda h, p: offered["key"], opener=opener)
    notes = []
    conn.open(params(), notes=notes)
    assert "stored" in notes[0] and opener.calls[0].pinned_key == KEY_A
    doc = db.host_keys.find_one({"host": "10.0.0.2"})
    assert doc["fingerprint"] == KEY_A.fingerprint and doc["fingerprint"].startswith("SHA256:")

    conn.open(params())  # same key → fine
    offered["key"] = KEY_B
    with pytest.raises(ConnectFailed, match="CHANGED") as exc:
        conn.open(params())
    assert exc.value.kind == "hostkey" and len(opener.calls) == 2  # the session (and password) never started
    assert db.host_keys.find_one({"host": "10.0.0.2"})["pending"]["fingerprint"] == KEY_B.fingerprint

    admin = client_for("admin")
    listing = admin.get("/api/hostkeys", params={"pending": True}).json()
    assert len(listing) == 1 and "key_b64" not in json_dump(listing)
    assert client_for("engineer").post(f"/api/hostkeys/{listing[0]['id']}/accept").status_code == 403
    accepted = admin.post(f"/api/hostkeys/{listing[0]['id']}/accept").json()
    assert accepted["fingerprint"] == KEY_B.fingerprint and accepted["pending"] is None
    conn.open(params())
    assert opener.calls[-1].pinned_key == KEY_B
    actions = [a["action"] for a in db.audit_log.find({"action": {"$regex": "^hostkey"}}, sort=[("seq", 1)])]
    assert actions == ["hostkey.first_seen", "hostkey.changed", "hostkey.accept"]


def test_keys_are_per_host_and_port(db):
    conn = Connector(db, probe=lambda h, p: KEY_A if p == 22 else KEY_B, opener=Opener())
    conn.open(params(port=22))
    conn.open(params(port=2222))
    assert db.host_keys.count_documents({"host": "10.0.0.2"}) == 2


@pytest.mark.parametrize("host", ["8.8.8.8", "203.0.113.5", None])
def test_p15_telnet_only_to_lab_addresses(db, host):
    opener = Opener()
    with pytest.raises(ConnectFailed, match="Telnet is allowed only"):
        Connector(db, probe=None, opener=opener).open(params("telnet_lab", host=host, port=23))
    assert opener.calls == []


@pytest.mark.parametrize("host", ["127.0.0.1", "192.168.1.10", "10.1.1.1", "172.16.0.5"])
def test_p15_telnet_lab_allowed_and_labelled(db, host):
    notes = []
    Connector(db, probe=None, opener=Opener()).open(params("telnet_lab", host=host, port=23), notes=notes)
    assert notes and notes[0].startswith("INSECURE")


def json_dump(obj) -> str:
    import json
    return json.dumps(obj, default=str)
