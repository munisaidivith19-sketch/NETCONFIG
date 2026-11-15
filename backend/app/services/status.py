"""Device status polling (Phase 4B): ping + TCP reachability of the management port, in the background.

No login is used: the poller only asks "does the address answer a ping?" and "is the SSH (or lab console) port
open?". Results go to ``devices.status``; a small summary per round goes to ``status_samples`` (kept 14 days by a
TTL index) for the Overview chart.

The poller never runs a shell. ``ping`` is started with a fixed argument list, and the address comes from the
inventory, where it was validated with the ``ipaddress`` module, and is checked again here.
"""

import ipaddress
import logging
import platform
import re
import shutil
import socket
import subprocess  # nosec B404 - fixed argument list, no shell (see ping())
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from pymongo.database import Database

from .. import clock

log = logging.getLogger("netconfig.status")

WINDOWS = platform.system() == "Windows"
_LATENCY = re.compile(r"time[=<]\s*(\d+(?:[.,]\d+)?)\s*ms", re.I)


def ping(host: str, timeout_s: float = 1.0) -> float | None:
    """Round-trip time in ms, or None. Windows' ping can exit 0 for "Destination host unreachable", so a reply
    counts only when the output has a TTL."""
    ip = ipaddress.ip_address(host)  # raises for anything that is not a plain address
    exe = shutil.which("ping")
    if not exe:
        return None
    if WINDOWS:
        args = [exe, "-n", "1", "-w", str(int(timeout_s * 1000))]
        if ip.version == 6:
            args.append("-6")
    else:
        args = [exe, "-c", "1", "-W", str(max(1, int(timeout_s)))]
        if ip.version == 6:
            args.append("-6")
    try:
        # The argument list is fixed and the address is an ipaddress object, so nothing can be injected.
        out = subprocess.run([*args, str(ip)], capture_output=True, text=True,  # noqa: S603  # nosec B603
                             timeout=timeout_s + 2, check=False).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    if "ttl=" not in out.lower():
        return None
    m = _LATENCY.search(out)
    return float(m.group(1).replace(",", ".")) if m else 0.0


def port_open(host: str, port: int, timeout_s: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def check(device: dict, pinger: Callable = ping, prober: Callable = port_open) -> dict:
    """One device. Reachable = the management port answers (or, without one, the ping does)."""
    host = device.get("mgmt_ip")
    conn = device.get("connection", {})
    method = conn.get("method")
    port = None
    if method in ("ssh", "telnet_lab"):
        port = conn.get("port") or (23 if method == "telnet_lab" else 22)
    latency = pinger(host)
    tcp = prober(host, port) if port else None
    reachable = tcp if tcp is not None else latency is not None
    return {"reachable": reachable, "ping": latency is not None, "latency_ms": latency, "port_open": tcp,
            "checked_at": clock.now(), "source": "poll"}


def pollable(db: Database) -> list[dict]:
    """Devices with a management address. Serial-only devices (first-time setup) have nothing to poll."""
    return list(db.devices.find({"mgmt_ip": {"$type": "string"}},
                                {"mgmt_ip": 1, "connection": 1, "status": 1}).limit(1000))


def poll_once(db: Database, simulate: bool = False, pinger: Callable = ping, prober: Callable = port_open,
              workers: int = 8) -> dict:
    devices = pollable(db)
    if simulate:  # SIMULATE_DEVICES: the simulated devices are always "up", nothing is sent to the network
        results = {d["_id"]: {"reachable": True, "ping": True, "latency_ms": 1.0, "port_open": True,
                              "checked_at": clock.now(), "source": "simulated"} for d in devices}
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ncs-poll") as pool:
            pairs = pool.map(lambda d: (d["_id"], check(d, pinger, prober)), devices)
            results = dict(pairs)
    for device_id, status in results.items():
        db.devices.update_one({"_id": device_id}, {"$set": {"status": status}})
    up = sum(1 for s in results.values() if s["reachable"])
    sample = {"at": clock.now(), "up": up, "down": len(results) - up,
              "unknown": db.devices.count_documents({}) - len(results)}
    db.status_samples.insert_one(sample)
    return sample


class StatusPoller:
    """Background thread: one poll round every ``interval`` seconds; ``wake()`` runs a round now."""

    def __init__(self, db: Database, interval: float, simulate: bool = False):
        self.db = db
        self.interval = interval
        self.simulate = simulate
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_round: float | None = None

    def start(self) -> None:
        if self.interval <= 0 or self._thread:
            return
        self._thread = threading.Thread(target=self._run, name="ncs-status", daemon=True)
        self._thread.start()

    def wake(self) -> None:
        self._wake.set()

    def shutdown(self) -> None:
        self._stop.set()
        self._wake.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                poll_once(self.db, self.simulate)
                self.last_round = time.monotonic()
            except Exception as exc:  # noqa: BLE001 - MongoDB down etc.: try again next round
                log.warning("status poll failed (%s)", type(exc).__name__)
            self._wake.wait(self.interval)
            self._wake.clear()
