"""Read-only ONVIF information from a camera (Phase 4A): manufacturer, model, firmware, serial, hardware id.

One SOAP call, GetDeviceInformation (ONVIF Device Management service, spec section 8.3.1), sent to
http://<camera>/onvif/device_service with a WS-Security UsernameToken PasswordDigest:

    digest = Base64( SHA-1( nonce + created + password ) )

so the password itself is not sent. The credentials are typed for this one request, held in memory and never
stored or logged (CLAUDE.md 8.3). Nothing on the camera is changed: NetConfig Studio never sends a "Set" call.

The reply comes from a device on the network, so it is treated as untrusted: it is size-limited, never parsed
by an XML parser (no entity expansion risk), and only five short allowlisted text fields are read from it.

Sources: ONVIF Core Specification (onvif.org/specs/core/ONVIF-Core-Specification.pdf) section 5.12 (security)
and 8.3.1 (GetDeviceInformation); OASIS WS-Security UsernameToken Profile 1.0.
"""

import base64
import hashlib
import http.client
import re
import secrets

from pydantic import SecretStr

from .. import clock

FIELDS = ("Manufacturer", "Model", "FirmwareVersion", "SerialNumber", "HardwareId")
MAX_REPLY = 64 * 1024
TIMEOUT = 8
_SAFE = re.compile(r"[^A-Za-z0-9 ._:/()+-]")
WSSE = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
WSU = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"
DIGEST = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest"
B64 = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary"


class OnvifError(Exception):
    """A safe message for the user (no secret, no raw exception text)."""


def _xml_text(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def envelope(username: str, password: SecretStr, *, nonce: bytes, created: str) -> str:
    digest = base64.b64encode(hashlib.sha1(nonce + created.encode() + password.get_secret_value().encode(),
                                           usedforsecurity=False).digest()).decode()
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">'
        f'<s:Header><Security xmlns="{WSSE}" s:mustUnderstand="1"><UsernameToken>'
        f"<Username>{_xml_text(username)}</Username>"
        f'<Password Type="{DIGEST}">{digest}</Password>'
        f'<Nonce EncodingType="{B64}">{base64.b64encode(nonce).decode()}</Nonce>'
        f'<Created xmlns="{WSU}">{created}</Created>'
        "</UsernameToken></Security></s:Header>"
        '<s:Body><GetDeviceInformation xmlns="http://www.onvif.org/ver10/device/wsdl"/></s:Body>'
        "</s:Envelope>"
    )


def parse_device_information(reply: str) -> dict[str, str]:
    """The five text fields of GetDeviceInformationResponse, cleaned to a safe character set."""
    if re.search(r"<(?:\w+:)?Fault\b", reply):
        reason = re.search(r"<(?:\w+:)?Text\b[^>]*>([^<]{0,200})<", reply)
        raise OnvifError("The camera refused the request" + (f": {_SAFE.sub('', reason.group(1))}" if reason else
                                                                 "."))
    info = {}
    for name in FIELDS:
        m = re.search(rf"<(?:\w+:)?{name}>([^<]{{0,128}})</(?:\w+:)?{name}>", reply)
        if m:
            info[name] = _SAFE.sub("", m.group(1)).strip()[:64]
    if not info:
        raise OnvifError("The reply is not an ONVIF device information response.")
    return info


def get_device_information(host: str, port: int, username: str, password: SecretStr) -> dict[str, str]:
    created = clock.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    body = envelope(username, password, nonce=secrets.token_bytes(16), created=created).encode()
    conn = http.client.HTTPConnection(host, port, timeout=TIMEOUT)
    try:
        conn.request("POST", "/onvif/device_service", body=body,
                     headers={"Content-Type": 'application/soap+xml; charset=utf-8; '
                              'action="http://www.onvif.org/ver10/device/wsdl/GetDeviceInformation"'})
        resp = conn.getresponse()
        reply = resp.read(MAX_REPLY + 1)
    except TimeoutError as exc:
        raise OnvifError(f"No answer from {host}:{port} (timeout).") from exc
    except OSError as exc:
        raise OnvifError(f"Cannot reach {host}:{port}.") from exc
    except http.client.HTTPException as exc:
        raise OnvifError(f"The camera's reply was not valid HTTP ({type(exc).__name__}).") from exc
    finally:
        conn.close()
    if len(reply) > MAX_REPLY:
        raise OnvifError("The camera's reply is too large.")
    if resp.status in (401, 403):
        raise OnvifError("The camera refused the login: check the username and password.")
    text = reply.decode("utf-8", errors="replace")
    if resp.status >= 400 and "Fault" not in text:
        raise OnvifError(f"The camera answered HTTP {resp.status}.")
    return parse_device_information(text)
