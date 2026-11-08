"""Push jobs: approval, credentials vault, background runner (docs/SYSTEM_DESIGN.md 5.1–5.5).

Lifecycle:  POST /jobs ─► awaiting_approval (production) ─approve─► ready ─run(+credentials)─► queued ─► push
                     └──► ready (lab device)
Credentials are accepted only by run(), only from "ready", and live only in the in-memory Vault until the
job finishes (removed in a ``finally`` block). Nothing secret is ever written to MongoDB.
"""

import hashlib
import json
import logging
import threading
from collections import defaultdict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.database import Database

from .. import clock
from ..config import Settings
from ..drivers.base import ModelInfo
from ..drivers.registry import get_driver
from ..errors import ApiError
from ..models.common import oid
from ..models.job import CANCELLABLE, RUNNING, TERMINAL, JobCreate, RunRequest
from ..models.plan import ConfigPlan
from ..security.sessions import SessionUser
from . import audit, planning, validation
from .connection import ConnectParams
from .hostkeys import Connector
from .push import PushEngine, StepInput

log = logging.getLogger("netconfig.jobs")
APPROVAL_HOURS = 24
INTERRUPTED = ("Interrupted (the app stopped) – verify the device state. "
               "A Cisco device restores its old config by its revert timer.")

# Allowed status changes (tests/unit/test_job_states.py checks this table).
TRANSITIONS: dict[str, set[str]] = {
    "awaiting_approval": {"ready", "cancelled", "expired"},
    "ready": {"queued", "cancelled"},
    "queued": {"connecting", "cancelled", "failed"},
    "connecting": {"backing_up", "failed", "cancelled"},
    "backing_up": {"checking", "failed", "cancelled"},
    "checking": {"applying", "blocked", "failed", "cancelled"},
    "applying": {"verifying", "rolling_back", "failed"},
    "verifying": {"saving", "success", "rolling_back", "rolled_back", "failed"},
    "saving": {"success", "failed"},
    "rolling_back": {"rolled_back", "failed"},
    **{t: set() for t in TERMINAL},
}


def can_move(src: str, dst: str) -> bool:
    return dst in TRANSITIONS.get(src, set())


@dataclass
class RunSecrets:
    request: RunRequest


class Vault:
    """job_id → secrets for that run. Memory only; ``pop`` is called in a finally block when the job ends."""

    def __init__(self):
        self._items: dict[str, RunSecrets] = {}
        self._lock = threading.Lock()

    def put(self, job_id: str, item: RunSecrets) -> None:
        with self._lock:
            self._items[job_id] = item

    def pop(self, job_id: str) -> RunSecrets | None:
        with self._lock:
            return self._items.pop(job_id, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def __contains__(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._items


def plan_hash(plan_doc: dict) -> str:
    return hashlib.sha256(json.dumps(plan_doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _who(doc: dict) -> SessionUser:
    r = doc["requested_by"]
    return SessionUser(session_id="", user_id=r["id"], username=r["username"], role="engineer")


# ------------------------------------------------------------------ service API
def create(db: Database, settings: Settings, user: SessionUser, body: JobCreate, request_id: str) -> dict:
    p = planning.prepare(db, settings, body.plan, device_id=body.device_id)
    if not p.ok:
        raise ApiError(422, "The plan is not valid for this device.", fields=p.errors)
    if p.device.get("connection", {}).get("method", "none") == "none":
        raise ApiError(422, "This device has no connection method.",
                       fields={"device_id": "set SSH, serial or lab console"})
    if p.production and p.driver_doc.get("support") == "experimental" and not settings.enable_experimental_drivers:
        raise ApiError(422, "Experimental driver on a production device.", fields={
            "device_id": f"{p.driver.os_name} is experimental (not lab-tested). Production pushes need "
                         "ENABLE_EXPERIMENTAL_DRIVERS=true."})
    now = clock.now()
    stored_plan = p.plan.without_secrets()
    doc = {
        "kind": "push",
        "status": "awaiting_approval" if p.production else "ready",
        "requested_by": {"id": user.user_id, "username": user.username},
        "approval": {"required": p.production,
                     "expires_at": now + timedelta(hours=APPROVAL_HOURS) if p.production else None,
                     "approved_by": None, "approved_at": None},
        "cancel_reason": None,
        "note": body.note,
        "plan": stored_plan,
        "plan_hash": plan_hash(stored_plan),
        "steps": [{
            "device_id": p.device["_id"], "device_name": p.device["name"], "os_id": p.model["os_id"],
            "connection": p.device.get("connection", {}).get("method"), "mgmt_ip": p.device.get("mgmt_ip"),
            "status": None, "commands": p.commands, "commands_hash": p.commands_hash,
            "verify_commands": p.verify_commands, "warnings": p.warnings,
            "timeline": [], "backup": "", "output": "", "checks": [], "error": None, "notes": [],
            "mgmt_interface": None, "started_at": None, "finished_at": None,
        }],
        "created_at": now, "updated_at": now, "finished_at": None,
    }
    doc["steps"][0]["status"] = doc["status"]
    doc["steps"][0]["timeline"].append({"state": doc["status"], "at": now})
    doc["_id"] = db.jobs.insert_one(doc).inserted_id
    audit.record(db, "job.create", who=user, target={"type": "job", "id": str(doc["_id"])},
                 details={"device": p.device["name"], "status": doc["status"], "plan_hash": doc["plan_hash"],
                          "commands_hash": p.commands_hash}, request_id=request_id)
    return doc


def get(db: Database, job_id: str) -> dict:
    doc = db.jobs.find_one({"_id": oid(job_id)})
    if not doc:
        raise ApiError(404, "Job not found.")
    return doc


def _move(db: Database, job_id: ObjectId, sources: tuple[str, ...], target: str,
          extra: dict | None = None) -> dict | None:
    """Atomic status change: succeeds only if the job is still in one of ``sources``."""
    if not all(can_move(s, target) for s in sources):
        raise ValueError(f"illegal job transition {sources} -> {target}")
    now = clock.now()
    update = {"$set": {"status": target, "steps.0.status": target, "updated_at": now, **(extra or {})},
              "$push": {"steps.0.timeline": {"state": target, "at": now}}}
    if target in TERMINAL:
        update["$set"]["finished_at"] = now
    return db.jobs.find_one_and_update({"_id": job_id, "status": {"$in": list(sources)}}, update,
                                       return_document=ReturnDocument.AFTER)


def expire_sweep(db: Database) -> int:
    count = 0
    for doc in db.jobs.find({"status": "awaiting_approval", "approval.expires_at": {"$lte": clock.now()}}, {"_id": 1}):
        if _move(db, doc["_id"], ("awaiting_approval",), "expired"):
            audit.record(db, "job.expire", target={"type": "job", "id": str(doc["_id"])})
            count += 1
    return count


def approve(db: Database, user: SessionUser, job_id: str, request_id: str) -> dict:
    doc = get(db, job_id)
    if doc["status"] != "awaiting_approval":
        raise ApiError(409, f"Only a job awaiting approval can be approved (status: {doc['status']}).")
    if doc["requested_by"]["id"] == user.user_id:
        raise ApiError(403, "Two-person rule: you cannot approve your own request.")
    now = clock.now()
    if now >= doc["approval"]["expires_at"]:
        expire_sweep(db)
        raise ApiError(409, "This request expired (not approved within 24 hours).")
    new = db.jobs.find_one_and_update(
        {"_id": doc["_id"], "status": "awaiting_approval", "approval.expires_at": {"$gt": now},
         "plan_hash": doc["plan_hash"]},
        {"$set": {"status": "ready", "steps.0.status": "ready", "updated_at": now,
                  "approval.approved_by": {"id": user.user_id, "username": user.username}, "approval.approved_at": now},
         "$push": {"steps.0.timeline": {"state": "ready", "at": now}}},
        return_document=ReturnDocument.AFTER)
    if not new:
        raise ApiError(409, "The job changed while you were approving it; reload and try again.")
    audit.record(db, "job.approve", who=user, target={"type": "job", "id": job_id},
                 details={"plan_hash": doc["plan_hash"], "commands_hash": doc["steps"][0]["commands_hash"]},
                 request_id=request_id)
    return new


def reject(db: Database, user: SessionUser, job_id: str, reason: str, request_id: str) -> dict:
    doc = get(db, job_id)
    new = _move(db, doc["_id"], ("awaiting_approval",), "cancelled",
                {"cancel_reason": "rejected", "rejected_by": {"id": user.user_id, "username": user.username},
                 "reject_note": reason})
    if not new:
        raise ApiError(409, f"Only a job awaiting approval can be rejected (status: {doc['status']}).")
    audit.record(db, "job.reject", who=user, target={"type": "job", "id": job_id}, details={"reason": reason},
                 request_id=request_id)
    return new


def _owner_or_admin(doc: dict, user: SessionUser) -> None:
    if doc["requested_by"]["id"] != user.user_id and user.role != "admin":
        raise ApiError(403, "Only the requester or an admin can do this.")


def merge_secrets(plan_doc: dict, req: RunRequest) -> ConfigPlan:
    """Put the run-time plan secrets back into the stored (secret-free) plan, in memory only."""
    data = json.loads(json.dumps(plan_doc))
    missing: dict[str, str] = {}  # RunRequest field name -> explanation
    ssh = data.get("ssh")
    wanted = [] if not ssh else [
        ("ssh_user_password", "password", True, f"the plan creates local user {ssh['username']}"),
        ("new_enable_secret", "enable_secret", bool(ssh.get("set_enable_secret")), "the plan sets the enable secret"),
    ]
    for field_name, plan_key, needed, why in wanted:
        value = getattr(req, field_name)
        if not needed:
            continue
        if value is None:
            missing[field_name] = f"required: {why}"
        else:
            ssh[plan_key] = value.get_secret_value()
    if missing:
        raise ApiError(422, "Some secrets are missing.", fields=missing)
    return ConfigPlan.model_validate(data)


class JobRunner:
    def __init__(self, db: Database, settings: Settings, connector=None, workers: int = 4):
        self.db = db
        self.settings = settings
        self.vault = Vault()
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ncs-job")
        self.device_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
        self.cancel_requests: set[str] = set()
        self.futures: dict[str, Future] = {}
        self._stop = threading.Event()
        if connector is None:
            if settings.simulate_devices:
                from .simulator import SimulatedConnector
                connector = SimulatedConnector()
            else:
                connector = Connector(db)
        self.connector = connector

    # -- lifecycle
    def start(self) -> None:
        self.recover()
        expire_sweep(self.db)
        threading.Thread(target=self._sweeper, name="ncs-expiry", daemon=True).start()

    def _sweeper(self) -> None:
        while not self._stop.wait(60):
            try:
                expire_sweep(self.db)
            except Exception as exc:  # noqa: BLE001 - keep sweeping; database may be down for a moment
                log.warning("expiry sweep failed (%s)", type(exc).__name__)

    def shutdown(self) -> None:
        self._stop.set()
        self.executor.shutdown(wait=False, cancel_futures=True)

    def recover(self) -> int:
        """Jobs left running by a crash or restart → failed. Cisco devices have reverted by their timer."""
        n = 0
        for doc in self.db.jobs.find({"status": {"$in": list(RUNNING)}}, {"_id": 1, "status": 1}):
            now = clock.now()
            self.db.jobs.update_one({"_id": doc["_id"], "status": doc["status"]}, {
                "$set": {"status": "failed", "steps.0.status": "failed", "finished_at": now, "updated_at": now,
                         "steps.0.error": {"command": None, "message": INTERRUPTED}},
                "$push": {"steps.0.timeline": {"state": "failed", "at": now}}})
            audit.record(self.db, "job.interrupted", result="failed", target={"type": "job", "id": str(doc["_id"])})
            n += 1
        return n

    # -- API actions
    def run(self, user: SessionUser, job_id: str, req: RunRequest, request_id: str) -> dict:
        doc = get(self.db, job_id)
        _owner_or_admin(doc, user)
        if doc["status"] != "ready":
            raise ApiError(409, f"Only a ready job can be run (status: {doc['status']}).")
        step = doc["steps"][0]
        device = self.db.devices.find_one({"_id": step["device_id"]})
        if not device:
            raise ApiError(409, "The device was removed from the inventory.")
        # Approval binding: the commands must still be exactly what was previewed (and approved).
        plan = merge_secrets(doc["plan"], req)
        p = planning.prepare(self.db, self.settings, plan, device_id=str(device["_id"]))
        if not p.ok or p.commands_hash != step["commands_hash"]:
            raise ApiError(409, "The device, catalog or plan changed since this job was created; create a new job.")
        if p.production and not doc["approval"]["required"]:
            raise ApiError(409, "The device is now tagged production and needs approval; create a new job.")
        busy = self.db.jobs.find_one({"_id": {"$ne": doc["_id"]}, "steps.device_id": device["_id"],
                                      "status": {"$in": list(RUNNING)}}, {"_id": 1})
        if busy:
            raise ApiError(409, "Another job is running on this device; wait for it to finish.")
        # Status first, credentials second: if the transition fails they never reach the vault.
        new = _move(self.db, doc["_id"], ("ready",), "queued",
                    {"run_by": {"id": user.user_id, "username": user.username}})
        if not new:
            raise ApiError(409, "The job is no longer ready.")
        self.vault.put(job_id, RunSecrets(req))
        audit.record(self.db, "job.run", who=user, target={"type": "job", "id": job_id},
                     details={"device": device["name"], "commands_hash": step["commands_hash"]}, request_id=request_id)
        self.futures[job_id] = self.executor.submit(self._execute, job_id)
        return new

    def cancel(self, user: SessionUser, job_id: str, request_id: str) -> dict:
        doc = get(self.db, job_id)
        _owner_or_admin(doc, user)
        if doc["status"] not in CANCELLABLE:
            raise ApiError(409, f"A job that is {doc['status']} cannot be cancelled (it is applying or finished).")
        if doc["status"] in ("awaiting_approval", "ready"):
            new = _move(self.db, doc["_id"], (doc["status"],), "cancelled", {"cancel_reason": "withdrawn"})
            if not new:
                raise ApiError(409, "The job changed; reload and try again.")
        else:
            self.cancel_requests.add(job_id)  # honoured before any config command is sent
            new = doc
        audit.record(self.db, "job.cancel", who=user, target={"type": "job", "id": job_id}, request_id=request_id)
        return new

    def wait(self, job_id: str, timeout: float = 30) -> None:
        fut = self.futures.get(job_id)
        if fut:
            fut.result(timeout=timeout)

    # -- worker
    def _execute(self, job_id: str) -> None:
        _id = ObjectId(job_id)
        try:
            secrets = self.vault.pop(job_id)  # taken out at once: the vault never outlives the run
            doc = self.db.jobs.find_one({"_id": _id})
            if secrets is None or doc is None:
                self._finish(_id, "failed", {"error": {"command": None, "message": "Credentials missing (restart?)."}})
                return
            step = doc["steps"][0]
            with self.device_locks[str(step["device_id"])]:
                self._push(doc, secrets.request)
        except Exception as exc:  # noqa: BLE001 - a job must always reach a terminal state
            log.error("job %s crashed (%s)", job_id, type(exc).__name__)
            self._finish(_id, "failed",
                         {"error": {"command": None, "message": f"Internal error ({type(exc).__name__})."}})
        finally:
            self.vault.pop(job_id)
            self.cancel_requests.discard(job_id)

    def _push(self, doc: dict, req: RunRequest) -> None:
        _id, step = doc["_id"], doc["steps"][0]
        job_id = str(_id)
        device = self.db.devices.find_one({"_id": step["device_id"]})
        model = self.db.catalog_models.find_one({"_id": device["model_id"]})
        driver = get_driver(model["os_id"], ModelInfo.from_doc(model), self.settings)
        plan = merge_secrets(doc["plan"], req)
        plan = validation.normalize_interfaces(plan, driver.normalize_interface)
        conn = device.get("connection", {})
        method = conn.get("method")
        params = ConnectParams(method=method, device_type=driver.netmiko_device_type, host=device.get("mgmt_ip"),
                               port=conn.get("port") or (23 if method == "telnet_lab" else 22),
                               username=req.username, password=req.password, secret=req.enable_secret,
                               serial_port=conn.get("serial_port"), baud=conn.get("baud") or 9600)
        secrets = [s for s in (req.password, req.enable_secret, req.ssh_user_password, req.new_enable_secret) if s]
        who = _who(doc)
        current = {"status": "queued"}

        def on_state(state: str) -> None:
            moved = _move(self.db, _id, (current["status"],), state,
                          {"steps.0.started_at": clock.now()} if state == "connecting" else None)
            if moved:
                current["status"] = state

        engine = PushEngine(open_connection=lambda prm, notes: self.connector.open(prm, who=who, notes=notes),
                            on_state=on_state, cancelled=lambda: job_id in self.cancel_requests)
        result = engine.run(StepInput(driver=driver, plan=plan, params=params, mgmt_ip=device.get("mgmt_ip"),
                                      secrets=secrets))
        extra = {"steps.0.commands_sent": result.commands, "steps.0.backup": result.backup,
                 "steps.0.output": result.output, "steps.0.checks": result.checks, "steps.0.error": result.error,
                 "steps.0.notes": result.notes, "steps.0.mgmt_interface": result.mgmt_interface,
                 "steps.0.finished_at": clock.now()}
        if result.status == "cancelled":
            extra["cancel_reason"] = "withdrawn"
        self._finish(_id, result.status, extra, current["status"])
        audit.record(self.db, f"job.{'rollback' if result.status == 'rolled_back' else 'finish'}",
                     result="ok" if result.status == "success" else "failed", who=who,
                     target={"type": "job", "id": job_id},
                     details={"status": result.status, "device": device["name"], "commands_hash": step["commands_hash"],
                              "error": result.error})
        if device.get("_id"):
            self.db.devices.update_one({"_id": device["_id"]}, {"$set": {
                "status.reachable": result.status != "failed" or bool(result.backup),  # backup read = it answered
                "status.checked_at": clock.now(), "status.last_job": {"id": job_id, "status": result.status}}})

    def _finish(self, _id: ObjectId, status: str, extra: dict, current: str | None = None) -> None:
        now = clock.now()
        update = {"$set": {"status": status, "steps.0.status": status, "updated_at": now, "finished_at": now,
                           **{k: v for k, v in extra.items() if not k.startswith("error")}},
                  "$push": {"steps.0.timeline": {"state": status, "at": now}}}
        if "error" in extra:
            update["$set"]["steps.0.error"] = extra["error"]
        for attempt in range(3):  # the final state matters most: retry if MongoDB blips
            try:
                self.db.jobs.update_one({"_id": _id}, update)
                return
            except Exception as exc:  # noqa: BLE001
                log.warning("could not save final job state (attempt %d, %s)", attempt + 1, type(exc).__name__)


def job_out(doc: dict, detail: bool = False) -> dict:
    def conv(v):
        if isinstance(v, ObjectId):
            return str(v)
        if isinstance(v, dict):
            return {k: conv(x) for k, x in v.items()}
        if isinstance(v, list):
            return [conv(x) for x in v]
        return v

    out = conv({k: v for k, v in doc.items() if k != "_id"})
    out["id"] = str(doc["_id"])
    if not detail:
        out.pop("plan", None)
        for s in out["steps"]:
            for k in ("backup", "output", "commands", "commands_sent", "checks", "verify_commands"):
                s.pop(k, None)
    return out
