"""Device connections. The push engine talks to the small `Connection` protocol below, so tests can use a
scripted FakeConnection and the dev simulator can stand in for a device (docs/TEST_PLAN.md section 5).

Netmiko does the real work (ADR 0003): SSH with a pinned host key, Telnet only to lab addresses, or a
serial console. Netmiko session logging is never enabled (CLAUDE.md 8.3).
"""

import base64
import hashlib
import logging
import os
import re
import socket
import tempfile
from dataclasses import dataclass
from typing import Protocol

from pydantic import SecretStr

log = logging.getLogger("netconfig.connection")

CONFIG_PROMPT = r"\(config[^)]*\)#"


class ConnectFailed(Exception):
    """Could not connect or log in. ``message`` is safe to show and store (no secrets, no raw exception)."""

    def __init__(self, kind: str, message: str):
        self.kind = kind  # auth | timeout | refused | hostkey | telnet | error
        self.message = message
        super().__init__(message)


class ConnectionLost(Exception):
    """The session broke after it was established."""


class Connection(Protocol):
    def show(self, command: str) -> str: ...
    def enter_config(self, command: str) -> str: ...
    def config_line(self, command: str, prompts: list[tuple[str, str]] | None = None) -> str: ...
    def exit_config(self) -> str: ...
    def exec(self, command: str) -> str: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class HostKey:
    key_type: str
    key_b64: str

    @property
    def fingerprint(self) -> str:
        """OpenSSH style: SHA256:<base64 without padding>."""
        digest = hashlib.sha256(base64.b64decode(self.key_b64)).digest()
        return "SHA256:" + base64.b64encode(digest).decode().rstrip("=")


@dataclass
class ConnectParams:
    method: str  # ssh | telnet_lab | serial
    device_type: str  # Netmiko device_type for SSH, e.g. "cisco_ios"
    host: str | None
    port: int | None
    username: str
    password: SecretStr
    secret: SecretStr | None = None
    serial_port: str | None = None
    baud: int = 9600
    pinned_key: HostKey | None = None  # SSH: the only host key that will be accepted


def probe_host_key(host: str, port: int, timeout: float = 10.0) -> HostKey:
    """Read the server's host key without authenticating (nothing secret is sent)."""
    import paramiko

    try:
        sock = socket.create_connection((host, port), timeout=timeout)
    except TimeoutError as exc:
        raise ConnectFailed("timeout", f"No answer from {host}:{port} (timeout).") from exc
    except OSError as exc:
        raise ConnectFailed("refused", f"Cannot open a connection to {host}:{port}.") from exc
    transport = paramiko.Transport(sock)
    try:
        transport.start_client(timeout=timeout)
        key = transport.get_remote_server_key()
        return HostKey(key.get_name(), key.get_base64())
    except Exception as exc:  # noqa: BLE001 - any SSH negotiation problem is reported the same way
        raise ConnectFailed("error", f"SSH negotiation with {host}:{port} failed ({type(exc).__name__}).") from exc
    finally:
        transport.close()


class NetmikoConnection:
    def __init__(self, conn):
        self._c = conn

    def _call(self, fn, *args, **kwargs) -> str:
        try:
            return fn(*args, **kwargs)
        except (OSError, EOFError) as exc:
            raise ConnectionLost(type(exc).__name__) from exc
        except Exception as exc:  # noqa: BLE001 - Netmiko/paramiko raise many types; all mean "session broke"
            raise ConnectionLost(type(exc).__name__) from exc

    def show(self, command: str) -> str:
        return self._call(self._c.send_command, command, read_timeout=90)

    def enter_config(self, command: str) -> str:
        return self._call(self._c.config_mode, config_command=command)

    def config_line(self, command: str, prompts: list[tuple[str, str]] | None = None) -> str:
        if not prompts:
            return self._call(self._c.send_config_set, [command], enter_config_mode=False, exit_config_mode=False,
                              cmd_verify=True, read_timeout=60)
        # A command that may ask a question (RSA "replace? [yes/no]"): wait for either the question or the
        # config prompt, answer once, then wait for the prompt. Never waits forever (read_timeout).
        expect = "|".join([CONFIG_PROMPT, *[p for p, _ in prompts]])
        out = self._call(self._c.send_command, command, expect_string=expect, read_timeout=180,
                         strip_prompt=False, strip_command=False, cmd_verify=False)
        for pattern, answer in prompts:
            if re.search(pattern, out):
                out += self._call(self._c.send_command, answer, expect_string=CONFIG_PROMPT, read_timeout=300,
                                  strip_prompt=False, strip_command=False, cmd_verify=False)
                break
        return out

    def exit_config(self) -> str:
        return self._call(self._c.exit_config_mode)

    def exec(self, command: str) -> str:
        return self._call(self._c.send_command, command, read_timeout=120)

    def close(self) -> None:
        try:
            self._c.disconnect()
        except Exception as exc:  # noqa: BLE001 - closing a broken session must never raise
            log.debug("disconnect failed (%s)", type(exc).__name__)


def open_netmiko(params: ConnectParams) -> NetmikoConnection:
    """Open a real session. SSH accepts ONLY ``params.pinned_key`` (paramiko RejectPolicy + known_hosts file),
    so a different key fails during the handshake – before the password is sent."""
    from netmiko import ConnectHandler
    from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException
    from paramiko.ssh_exception import BadHostKeyException, SSHException

    common = {"username": params.username, "password": params.password.get_secret_value(),
              "secret": params.secret.get_secret_value() if params.secret else "",
              "session_log": None, "fast_cli": False, "conn_timeout": 15, "auth_timeout": 20, "banner_timeout": 20}
    known_hosts = None
    if params.method == "ssh":
        if params.pinned_key is None:
            raise ConnectFailed("hostkey", "No pinned host key; refusing to connect.")
        fd, known_hosts = tempfile.mkstemp(prefix="ncs-known-", suffix=".txt")
        name = params.host if params.port == 22 else f"[{params.host}]:{params.port}"
        with os.fdopen(fd, "w", encoding="ascii") as fh:
            fh.write(f"{name} {params.pinned_key.key_type} {params.pinned_key.key_b64}\n")
        args = {**common, "device_type": params.device_type, "host": params.host, "port": params.port,
                "ssh_strict": True, "system_host_keys": False, "alt_host_keys": True, "alt_key_file": known_hosts,
                "use_keys": False, "allow_agent": False}
    elif params.method == "telnet_lab":
        args = {**common, "device_type": f"{params.device_type}_telnet", "host": params.host, "port": params.port}
    elif params.method == "serial":
        args = {**common, "device_type": f"{params.device_type}_serial",
                "serial_settings": {"port": params.serial_port, "baudrate": params.baud}}
    else:
        raise ConnectFailed("error", f"Connection method {params.method!r} cannot be used to configure.")
    try:
        conn = ConnectHandler(**args)
        if params.secret is not None or not conn.check_enable_mode():
            conn.enable()
        return NetmikoConnection(conn)
    except NetmikoAuthenticationException as exc:
        raise ConnectFailed("auth", "Login failed: check the username and password (not retried).") from exc
    except BadHostKeyException as exc:
        raise ConnectFailed("hostkey", "The device's SSH host key does not match the pinned key.") from exc
    except NetmikoTimeoutException as exc:
        raise ConnectFailed("timeout", "The device did not answer in time.") from exc
    except SSHException as exc:
        raise ConnectFailed("hostkey" if "host key" in str(exc).lower() else "error",
                            f"SSH failed ({type(exc).__name__}).") from exc
    except Exception as exc:  # noqa: BLE001 - message is sanitised: only the exception type is kept
        raise ConnectFailed("error", f"Connection failed ({type(exc).__name__}).") from exc
    finally:
        if known_hosts:
            os.unlink(known_hosts)
