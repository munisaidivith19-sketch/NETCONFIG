"""Access points and cameras (Phase 4A step 4): uplink switch port, read-only ONVIF information."""

import base64
import hashlib

import pytest
from pydantic import SecretStr

from app.api import devices as devices_api
from app.services import onvif

REPLY = """<?xml version="1.0"?><SOAP-ENV:Envelope xmlns:SOAP-ENV="http://www.w3.org/2003/05/soap-envelope"
xmlns:tds="http://www.onvif.org/ver10/device/wsdl"><SOAP-ENV:Body><tds:GetDeviceInformationResponse>
<tds:Manufacturer>AXIS</tds:Manufacturer><tds:Model>P3245-V</tds:Model>
<tds:FirmwareVersion>10.12.153</tds:FirmwareVersion><tds:SerialNumber>ACCC8E000001</tds:SerialNumber>
<tds:HardwareId>7A9<script>x</script></tds:HardwareId></tds:GetDeviceInformationResponse></SOAP-ENV:Body>
</SOAP-ENV:Envelope>"""
FAULT = """<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Body><s:Fault><s:Code>
<s:Value>s:Sender</s:Value></s:Code><s:Reason><s:Text xml:lang="en">Sender not Authorized</s:Text></s:Reason>
</s:Fault></s:Body></s:Envelope>"""


@pytest.fixture(autouse=True)
def _reset_limit():
    devices_api.onvif_limit.reset()


def add(client, name, model_id, ip=None, **extra):
    body = {"name": name, "model_id": model_id, "mgmt_ip": ip, "connection": {"method": "none"}, **extra}
    if model_id.startswith("cisco-iosvl2"):
        body["connection"] = {"method": "ssh"}
    return client.post("/api/devices", json=body)


def test_password_digest_follows_ws_security():
    nonce, created = b"0123456789abcdef", "2026-11-11T10:00:00Z"
    xml = onvif.envelope("viewer", SecretStr("Pa55word"), nonce=nonce, created=created)
    want = base64.b64encode(hashlib.sha1(nonce + created.encode() + b"Pa55word").digest()).decode()  # noqa: S324 - SHA-1 is what WS-Security mandates
    assert want in xml and "Pa55word" not in xml
    assert base64.b64encode(nonce).decode() in xml and "<GetDeviceInformation" in xml


def test_reply_parsing_keeps_only_safe_text():
    info = onvif.parse_device_information(REPLY)
    assert info["Manufacturer"] == "AXIS" and info["Model"] == "P3245-V" and info["SerialNumber"] == "ACCC8E000001"
    assert "HardwareId" not in info  # text with markup inside is not a plain field
    with pytest.raises(onvif.OnvifError, match="Sender not Authorized"):
        onvif.parse_device_information(FAULT)
    with pytest.raises(onvif.OnvifError):
        onvif.parse_device_information("<html>hello</html>")


def test_ap_uplink_must_be_a_switch_port(client_for):
    eng = client_for("engineer")
    sw = add(eng, "sw1", "cisco-iosvl2", "10.0.0.2").json()
    ok = add(eng, "ap1", "cisco-c9120axi", uplink={"device_id": sw["id"], "interface": "GigabitEthernet0/1"})
    assert ok.status_code == 201, ok.text
    assert ok.json()["uplink"] == {"device_id": sw["id"], "interface": "GigabitEthernet0/1"}
    bad_port = add(eng, "ap2", "cisco-c9120axi", uplink={"device_id": sw["id"], "interface": "Gi9/9"})
    assert bad_port.status_code == 422 and "uplink.interface" in bad_port.json()["error"]["fields"]
    not_switch = add(eng, "ap3", "cisco-c9120axi", uplink={"device_id": ok.json()["id"], "interface": "x1"})
    assert not_switch.status_code == 422
    on_a_switch = add(eng, "sw2", "cisco-iosvl2", "10.0.0.3",
                      uplink={"device_id": sw["id"], "interface": "GigabitEthernet0/1"})
    assert on_a_switch.status_code == 422
    injected = add(eng, "ap4", "cisco-c9120axi", uplink={"device_id": sw["id"], "interface": "Gi0/1\nreload"})
    assert injected.status_code == 422


def test_onvif_read_stores_facts_never_the_password(client_for, db, monkeypatch):
    eng, viewer = client_for("engineer"), client_for("viewer")
    cam = add(eng, "cam1", "axis-p3245-v", "10.0.5.20").json()
    seen = {}

    def fake(host, port, username, password):
        seen.update(host=host, port=port, password=password.get_secret_value())
        return onvif.parse_device_information(REPLY)

    monkeypatch.setattr(onvif, "get_device_information", fake)
    body = {"username": "viewer", "password": "Cam3ra-Secret", "port": 8080}
    assert viewer.post(f"/api/devices/{cam['id']}/onvif", json=body).status_code == 403
    r = eng.post(f"/api/devices/{cam['id']}/onvif", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["facts"]["model"] == "P3245-V" and seen == {"host": "10.0.5.20", "port": 8080,
                                                                "password": "Cam3ra-Secret"}
    assert "Cam3ra-Secret" not in str(db.devices.find_one({"name": "cam1"}))
    assert "Cam3ra-Secret" not in str(list(db.audit_log.find({"action": "device.onvif_read"})))
    assert eng.post(f"/api/devices/{cam['id']}/onvif", json={**body, "extra": 1}).status_code == 422


def test_onvif_only_for_cameras_and_errors_are_safe(client_for, monkeypatch):
    eng = client_for("engineer")
    sw = add(eng, "sw1", "cisco-iosvl2", "10.0.0.2").json()
    body = {"username": "u", "password": "p"}
    assert eng.post(f"/api/devices/{sw['id']}/onvif", json=body).status_code == 422
    cam = add(eng, "cam1", "axis-p3245-v", "10.0.5.20").json()

    def refused(*_args):
        raise onvif.OnvifError("The camera refused the login: check the username and password.")

    monkeypatch.setattr(onvif, "get_device_information", refused)
    r = eng.post(f"/api/devices/{cam['id']}/onvif", json=body)
    assert r.status_code == 502 and "refused the login" in r.json()["error"]["message"]


def test_deleting_a_switch_clears_the_uplinks_that_point_at_it(client_for, db):
    """Phase 4D review: a stale uplink made every later edit of the AP fail with 'not a switch'."""
    eng, admin = client_for("engineer"), client_for("admin")
    sw = add(eng, "sw1", "cisco-iosvl2", "10.0.0.2").json()
    ap = add(eng, "ap1", "cisco-c9120axi", uplink={"device_id": sw["id"], "interface": "GigabitEthernet0/1"}).json()
    assert admin.delete(f"/api/devices/{sw['id']}").status_code == 200
    assert eng.get(f"/api/devices/{ap['id']}").json().get("uplink") is None
    entry = db.audit_log.find_one({"action": "device.delete"})
    assert entry["details"]["uplinks_cleared"] == 1
