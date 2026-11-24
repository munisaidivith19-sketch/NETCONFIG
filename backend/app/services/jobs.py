"""Push jobs: approval, credentials vault, background runner (docs/SYSTEM_DESIGN.md 5.1–5.7).

Lifecycle:  POST /jobs ─► awaiting_approval (production) ─approve─► ready ─run(+credentials)─► queued ─► push
                     └──► ready (lab device)
Credentials are accepted only by run(), only from "ready", and live only in the in-memory Vault until the
job finishes (removed in a ``finally`` block). Nothing secret is ever written to MongoDB.

A job has one step per device. Four kinds (services/wizards.py builds them):
  push       one device
  multi      the same plan on 2–20 switches, one after another (stops at the first failure by default)
  link       both ends of a router link: A and B are applied and verified, then confirmed together;
             if either side fails before the confirms, the other is rolled back too. Only if B's confirm
             fails right after A's (seconds apart) is A left changed – then A is not saved and the job
             reports a MANUAL ACTION
  bootstrap  first-time setup over a console, then an SSH test login; only if it works does the device
             switch to SSH
"""

import hashlib
import json
import logging
import threading
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import ExitStack
from datetime import timedelta

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError, PyMongoError

from .. import clock
from ..config import Settings
from ..drivers.base import ModelInfo
from ..drivers.registry import get_driver
from ..errors import ApiError
from ..models.common import oid
from ..models.job import CANCELLABLE, FAILED, RUNNING, TERMINAL, JobCreate, RunRequest
from ..models.plan import ConfigPlan
from ..security.rbac import require_owner_or_admin
from ..security.sessions import SessionUser
from . import audit, planning, validation, wizards
from .connection import ConnectFailed, ConnectParams, default_port
from .hostkeys import Connector
from .push import Held, PushEngine, StepInput, StepResult

log = logging.getLogger("netconfig.jobs")
APPROVAL_HOURS = 24
INTERRUPTED = ("Interrupted (the app stopped) – verify the device state. "
               "A device with a rollback timer (Cisco, Junos, EOS, AOS-CX) restores its old config by itself.")
SKIPPED = "cancelled"  # a step that never started (an earlier step failed, or the job was withdrawn)

# Allowed status changes of one step (tests/unit/test_job_states.py checks this table). The job status
# follows its active step while running; before and after, every step has the job's status.
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


class Vault:
    """job_id → the run request (login + plan secrets). Memory only; ``pop`` is called in a finally block when
    the job ends."""

    def __init__(self):
        self._items: dict[str, RunRequest] = {}
        self._lock = threading.Lock()

    def put(self, job_id: str, req: RunRequest) -> None:
        with self._lock:
            self._items[job_id] = req

    def pop(self, job_id: str) -> RunRequest | None:
        with self._lock:
            return self._items.pop(job_id, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


def plan_hash(plan_doc: dict) -> str:
    return hashlib.sha256(json.dumps(plan_doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def stored_request(body: JobCreate) -> dict:
    """The job request as stored (and re-built at /run): the plan's secrets are removed, never masked."""
    data = body.model_dump(mode="json", exclude={"plan"})
    data["plan"] = body.plan.without_secrets() if body.plan else None
    return data


def request_of(doc: dict) -> dict:
    """The stored request; jobs created before Phase 3B only kept device + plan."""
    return doc.get("request") or {"device_id": str(doc["steps"][0]["device_id"]), "plan": doc["plan"],
                                  "note": doc.get("note", "")}


def aggregate(statuses: list[str]) -> str:
    """Job status from its step statuses (docs/SYSTEM_DESIGN.md 5.4)."""
    if all(s == "success" for s in statuses):
        return "success"
    if "success" in statuses:
        return "failed"  # partly applied: some devices changed, others not
    for s in FAILED:
        if s in statuses:
            return s
    return "cancelled"


def _who(doc: dict) -> SessionUser:
    r = doc["requested_by"]
    return SessionUser(session_id="", user_id=r["id"], username=r["username"], role="engineer")


def _failed_update(message: str) -> dict:
    """Job → failed; every step that has not finished yet → failed with ``message`` (array filter ``s``)."""
    now = clock.now()
    return {"$set": {"status": "failed", "finished_at": now, "updated_at": now, "summary": message,
                     "steps.$[s].status": "failed", "steps.$[s].error": {"command": None, "message": message}},
            "$push": {"steps.$[s].timeline": {"state": "failed", "at": now}}}


def _step_doc(b: wizards.BuiltStep, status: str, now) -> dict:
    p = b.prepared
    return {
        "device_id": p.device["_id"], "device_name": p.device["name"], "role": b.role, "os_id": p.model["os_id"],
        "connection": p.device.get("connection", {}).get("method"), "mgmt_ip": p.device.get("mgmt_ip"),
        "status": status, "plan": p.plan.without_secrets(), "commands": p.commands,
        "commands_hash": p.commands_hash, "verify_commands": p.verify_commands, "warnings": p.warnings,
        "timeline": [{"state": status, "at": now}], "backup": "", "output": "", "checks": [], "error": None,
        "notes": [], "mgmt_interface": None, "started_at": None, "finished_at": None,
    }


# ------------------------------------------------------------------ service API
def preview(db: Database, settings: Settings, body: JobCreate) -> dict:
    """What POST /jobs would create, without creating it (the wizards' preview step)."""
    b = wizards.build(db, settings, body)
    return {
        "ok": b.ok, "kind": b.kind, "errors": b.errors, "warnings": b.warnings, "checks": b.checks,
        "production": b.production, "bootstrap": b.bootstrap,
        "steps": [{"device_id": str(s.prepared.device["_id"]), "device_name": s.prepared.device["name"],
                   "role": s.role, "ok": s.prepared.ok, "commands": s.prepared.commands,
                   "verify_commands": s.prepared.verify_commands, "warnings": s.prepared.warnings,
                   "commands_hash": s.prepared.commands_hash if s.prepared.ok else None,
                   "revert_minutes": s.prepared.plan.revert_minutes} for s in b.steps if s.prepared.device],
    }


def create(db: Database, settings: Settings, user: SessionUser, body: JobCreate, request_id: str) -> dict:
    b = wizards.build(db, settings, body)
    if not b.ok:
        raise ApiError(422, "The plan is not valid for this device." if b.kind == "push"
                       else "The request is not valid.", fields=b.errors)
    for s in b.steps:
        p = s.prepared
        if p.device.get("connection", {}).get("method", "none") == "none":
            raise ApiError(422, f"{p.device['name']} has no connection method.",
                           fields={"device_id": "set SSH, serial or lab console"})
        if p.production and p.driver_doc.get("support") == "experimental" and not settings.enable_experimental_drivers:
            raise ApiError(422, "This production device uses an experimental (not lab-tested) driver, so it cannot be "
                                "pushed to.", fields={
                "device_id": f"{p.driver.os_name} is experimental (not lab-tested). Production pushes need "
                             "ENABLE_EXPERIMENTAL_DRIVERS=true."})
    now = clock.now()
    status = "awaiting_approval" if b.production else "ready"
    request = stored_request(body)
    steps = [_step_doc(s, status, now) for s in b.steps]
    doc = {
        "kind": b.kind,
        "status": status,
        "requested_by": {"id": user.user_id, "username": user.username},
        "approval": {"required": b.production,
                     "expires_at": now + timedelta(hours=APPROVAL_HOURS) if b.production else None,
                     "approved_by": None, "approved_at": None},
        "cancel_reason": None,
        "note": body.note,
        "request": request,
        "plan": steps[0]["plan"],  # the (first) device's plan; every step also keeps its own
        "plan_hash": plan_hash(request),
        "link_checks": b.checks,
        "bootstrap": b.bootstrap,
        "stop_on_failure": body.stop_on_failure,
        "summary": None,
        "steps": steps,
        "created_at": now, "updated_at": now, "finished_at": None,
    }
    doc["_id"] = db.jobs.insert_one(doc).inserted_id
    audit.record(db, "job.create", who=user, target={"type": "job", "id": str(doc["_id"])},
                 details={"kind": b.kind, "devices": [s["device_name"] for s in steps], "status": status,
                          "plan_hash": doc["plan_hash"], "commands_hash": [s["commands_hash"] for s in steps]},
                 request_id=request_id)
    # The commands that will really be pushed are frozen here, for every job kind and route: log the custom ones.
    for s in b.steps:
        if custom := planning.custom_audit(s.prepared):
            device = s.prepared.device
            audit.record(db, "job.custom_commands", who=user, request_id=request_id, details=custom,
                         target={"type": "device", "id": str(device["_id"]), "name": device["name"],
                                 "job": str(doc["_id"])})
    return doc


def get(db: Database, job_id: str) -> dict:
    doc = db.jobs.find_one({"_id": oid(job_id)})
    if not doc:
        raise ApiError(404, "Job not found.")
    return doc


def _move(db: Database, job_id: ObjectId, sources: tuple[str, ...], target: str,
          extra: dict | None = None, match: dict | None = None) -> dict | None:
    """Atomic status change of the whole job (all steps) before it runs: succeeds only if the job is still in
    one of ``sources`` (and still matches ``match``)."""
    if not all(can_move(s, target) for s in sources):
        raise ValueError(f"illegal job transition {sources} -> {target}")
    now = clock.now()
    update = {"$set": {"status": target, "steps.$[].status": target, "updated_at": now, **(extra or {})},
              "$push": {"steps.$[].timeline": {"state": target, "at": now}}}
    if target in TERMINAL:
        update["$set"]["finished_at"] = now
    return db.jobs.find_one_and_update({"_id": job_id, "status": {"$in": list(sources)}, **(match or {})}, update,
                                       return_document=ReturnDocument.AFTER)


def _expire(db: Database, job_id: ObjectId) -> dict | None:
    new = _move(db, job_id, ("awaiting_approval",), "expired")
    if new:
        audit.record(db, "job.expire", target={"type": "job", "id": str(job_id)})
    return new


def expire_sweep(db: Database) -> int:
    """All overdue approval requests → expired. Run by the background sweeper every minute."""
    due = db.jobs.find({"status": "awaiting_approval", "approval.expires_at": {"$lte": clock.now()}}, {"_id": 1})
    return sum(1 for doc in due if _expire(db, doc["_id"]))


def get_current(db: Database, job_id: str) -> dict:
    """get(), with this one job expired if its approval is overdue (the sweeper may be up to a minute late)."""
    doc = get(db, job_id)
    if doc["status"] == "awaiting_approval" and clock.now() >= doc["approval"]["expires_at"]:
        return _expire(db, doc["_id"]) or get(db, job_id)
    return doc


def approve(db: Database, user: SessionUser, job_id: str, request_id: str) -> dict:
    doc = get(db, job_id)
    if doc["status"] != "awaiting_approval":
        raise ApiError(409, f"Only a job awaiting approval can be approved (status: {doc['status']}).")
    if doc["requested_by"]["id"] == user.user_id:
        raise ApiError(403, "Two-person rule: you cannot approve your own request.")
    now = clock.now()
    if now >= doc["approval"]["expires_at"]:
        _expire(db, doc["_id"])
        raise ApiError(409, "This request expired (not approved within 24 hours).")
    new = _move(db, doc["_id"], ("awaiting_approval",), "ready",
                {"approval.approved_by": {"id": user.user_id, "username": user.username}, "approval.approved_at": now},
                match={"approval.expires_at": {"$gt": now}, "plan_hash": doc["plan_hash"]})
    if not new:
        raise ApiError(409, "The job changed while you were approving it; reload and try again.")
    audit.record(db, "job.approve", who=user, target={"type": "job", "id": job_id},
                 details={"plan_hash": doc["plan_hash"], "commands_hash": [s["commands_hash"] for s in doc["steps"]]},
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
    require_owner_or_admin(doc["requested_by"], user, "Only the requester or an admin can do this.")


def merge_secrets(plan_doc: dict, req: RunRequest) -> ConfigPlan:
    """Put the run-time plan secrets back into the stored (secret-free) plan, in memory only."""
    data = json.loads(json.dumps(plan_doc))
    missing: dict[str, str] = {}  # RunRequest field name -> explanation
    ssh = data.get("ssh")
    if ssh:
        if req.ssh_user_password is None:
            missing["ssh_user_password"] = f"required: the plan creates local user {ssh['username']}"
        else:
            ssh["password"] = req.ssh_user_password.get_secret_value()
        if ssh.get("set_enable_secret"):
            if req.new_enable_secret is None:
                missing["new_enable_secret"] = "required: the plan sets the enable secret"  # noqa: S105  # nosec B105
            else:
                ssh["enable_secret"] = req.new_enable_secret.get_secret_value()
    if missing:
        raise ApiError(422, "The plan needs secrets that were not entered; fill in the marked fields.", fields=missing)
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
        # Set once jobs left running by the last process are marked failed. Until then no job may start:
        # recovery would mark it failed too.
        self.recovered = threading.Event()
        self.startup_retry_seconds = 5.0
        if connector is None:
            if settings.demo_mode and not settings.simulate_devices:  # also refused by Settings.check_demo
                raise RuntimeError("DEMO_MODE needs SIMULATE_DEVICES=true: the public demo never reaches real devices.")
            if settings.simulate_devices:
                from .simulator import SimulatedConnector
                connector = SimulatedConnector()
            else:
                connector = Connector(db)
        self.connector = connector

    # -- lifecycle
    def start(self, prepare: Callable[[], None] = lambda: None) -> None:
        """Startup work that needs MongoDB (``prepare`` = indexes and seed, then crash recovery). MongoDB may
        start after the app (a Windows service at login), so a background thread retries until it is done."""
        retry = None if self._startup(prepare) else prepare
        threading.Thread(target=self._sweeper, args=(retry,), name="ncs-expiry", daemon=True).start()

    def _startup(self, prepare: Callable[[], None]) -> bool:
        try:
            prepare()
            self.recover()
            expire_sweep(self.db)
            return True
        except Exception as exc:  # noqa: BLE001 - database not up yet; retried by the sweeper thread
            log.warning("MongoDB not available (%s); startup tasks will be retried.", type(exc).__name__)
            return False

    def _sweeper(self, prepare: Callable[[], None] | None = None) -> None:
        if prepare is not None:
            while not self._startup(prepare):
                if self._stop.wait(self.startup_retry_seconds):
                    return
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
            self.db.jobs.update_one({"_id": doc["_id"], "status": doc["status"]}, _failed_update(INTERRUPTED),
                                    array_filters=[{"s.status": {"$in": list(RUNNING)}}])
            audit.record(self.db, "job.interrupted", result="failed", target={"type": "job", "id": str(doc["_id"])})
            n += 1
        self.recovered.set()
        return n

    # -- API actions
    def run(self, user: SessionUser, job_id: str, req: RunRequest, request_id: str) -> dict:
        if not self.recovered.is_set():
            raise ApiError(503, "NetConfig Studio is still starting (waiting for the database). Try again shortly.")
        doc = get(self.db, job_id)
        _owner_or_admin(doc, user)
        if doc["status"] != "ready":
            raise ApiError(409, f"Only a ready job can be run (status: {doc['status']}).")
        devices = [self.db.devices.find_one({"_id": s["device_id"]}) for s in doc["steps"]]
        if not all(devices):
            raise ApiError(409, "A device of this job was removed from the inventory.")
        for s, device in zip(doc["steps"], devices, strict=True):
            # The job goes where it was previewed and approved: same address, same connection method.
            if (device.get("mgmt_ip"), device.get("connection", {}).get("method")) != (s.get("mgmt_ip"),
                                                                                      s.get("connection")):
                raise ApiError(409, f"{device['name']}'s address or connection changed since this job was created; "
                                    "create a new job.")
        missing = {}
        for device in devices:
            if device.get("connection", {}).get("method") == "ssh" and req.login_for(str(device["_id"]))[0] is None:
                missing["username"] = f"required: {device['name']} is reached over SSH"
        if missing:
            raise ApiError(422, "The device login is missing.", fields=missing)
        # Approval binding: rebuild from the stored request; the commands must still be exactly what was
        # previewed (and approved) for every device.
        built = wizards.build(self.db, self.settings, JobCreate.model_validate(request_of(doc)))
        hashes = [s.prepared.commands_hash for s in built.steps]
        if not built.ok or hashes != [s["commands_hash"] for s in doc["steps"]]:
            raise ApiError(409, "A device, the catalog or the plan changed since this job was created; "
                                "create a new job.")
        if built.production and not doc["approval"]["required"]:
            raise ApiError(409, "A device is now tagged production and needs approval; create a new job.")
        for s in doc["steps"]:
            merge_secrets(s.get("plan") or doc["plan"], req)  # fail now (422) rather than in the background
        busy = self.db.jobs.find_one({"_id": {"$ne": doc["_id"]}, "status": {"$in": list(RUNNING)},
                                      "steps.device_id": {"$in": [d["_id"] for d in devices]}}, {"_id": 1})
        if busy:
            raise ApiError(409, "Another job is running on one of these devices; wait for it to finish.")
        # Status first, credentials second: if the transition fails they never reach the vault.
        new = _move(self.db, doc["_id"], ("ready",), "queued",
                    {"run_by": {"id": user.user_id, "username": user.username}})
        if not new:
            raise ApiError(409, "This job can no longer be run: it was cancelled, expired or already started. "
                           "Reload to see its status.")
        self.vault.put(job_id, req)
        audit.record(self.db, "job.run", who=user, target={"type": "job", "id": job_id},
                     details={"kind": doc["kind"], "devices": [d["name"] for d in devices],
                              "commands_hash": [s["commands_hash"] for s in doc["steps"]]}, request_id=request_id)
        fut = self.executor.submit(self._execute, job_id)
        self.futures[job_id] = fut
        fut.add_done_callback(lambda _: self.futures.pop(job_id, None))
        return new

    def cancel(self, user: SessionUser, job_id: str, request_id: str) -> dict:
        doc = get(self.db, job_id)
        _owner_or_admin(doc, user)
        # Several switches: also while running. Switches not started yet are skipped; the switch in progress
        # stops too if no configuration command was sent to it yet, otherwise it is finished first.
        allowed = CANCELLABLE + (RUNNING if doc.get("kind") == "multi" else ())
        if doc["status"] not in allowed:
            raise ApiError(409, f"A job that is {doc['status']} cannot be cancelled (it is applying or finished).")
        if doc["status"] in ("awaiting_approval", "ready"):
            new = _move(self.db, doc["_id"], (doc["status"],), "cancelled", {"cancel_reason": "withdrawn"})
            if not new:
                raise ApiError(409, "The job changed; reload and try again.")
            result = "ok"
        else:
            # Only a job whose worker is still running can be stopped. Re-check after adding: if the worker
            # finished in between, its cleanup has already run and nobody would ever read (or remove) the request.
            self.cancel_requests.add(job_id)
            if job_id not in self.futures:
                self.cancel_requests.discard(job_id)
                raise ApiError(409, "The job has already finished; reload to see its result.")
            # A request, not a result: it is honoured only if no configuration command was sent yet. The job's
            # final status (cancelled or not) and its notes record what really happened.
            new, result = doc, "requested"
        audit.record(self.db, "job.cancel", result=result, who=user, target={"type": "job", "id": job_id},
                     details={"status_when_requested": doc["status"]}, request_id=request_id)
        return new

    def wait(self, job_id: str, timeout: float = 30) -> None:
        fut = self.futures.get(job_id)
        if fut:
            fut.result(timeout=timeout)

    # -- worker
    def _execute(self, job_id: str) -> None:
        _id = ObjectId(job_id)
        try:
            req = self.vault.pop(job_id)  # taken out at once: the vault never outlives the run
            doc = self.db.jobs.find_one({"_id": _id})
            if req is None or doc is None:
                self._fail_job(_id, "Credentials missing (restart?).")
                return
            with ExitStack() as stack:
                # Sorted, so two jobs that share devices always lock them in the same order (no deadlock).
                for device_id in sorted({str(s["device_id"]) for s in doc["steps"]}):
                    stack.enter_context(self.device_locks[device_id])
                Execution(self, doc, req).run()
        except Exception as exc:  # noqa: BLE001 - a job must always reach a terminal state
            log.error("job %s crashed (%s)", job_id, type(exc).__name__)
            self._fail_job(_id, f"Internal error ({type(exc).__name__}).")
        finally:
            self.vault.pop(job_id)
            self.cancel_requests.discard(job_id)

    def _fail_job(self, _id: ObjectId, message: str) -> None:
        self._save(_id, _failed_update(message), array_filters=[{"s.status": {"$nin": list(TERMINAL)}}])

    def _save(self, _id: ObjectId, update: dict, array_filters=None) -> None:
        for attempt in range(3):  # the final state matters most: retry if MongoDB blips
            try:
                self.db.jobs.update_one({"_id": _id}, update, array_filters=array_filters)
                return
            except Exception as exc:  # noqa: BLE001
                log.warning("could not save job state (attempt %d, %s)", attempt + 1, type(exc).__name__)


class Execution:
    """One run of one job: builds the per-device inputs, runs the steps for the job's kind, stores results."""

    def __init__(self, runner: JobRunner, doc: dict, req: RunRequest):
        self.r, self.db, self.doc, self.req = runner, runner.db, doc, req
        self._id = doc["_id"]
        self.job_id = str(self._id)
        self.who = _who(doc)
        self.current = [s["status"] for s in doc["steps"]]  # "queued" for every step
        self.devices = [self.db.devices.find_one({"_id": s["device_id"]}) for s in doc["steps"]]

    def run(self) -> None:
        self._finish(self._link() if self.doc["kind"] == "link" else self._in_order())

    def _in_order(self) -> list[StepResult]:
        """push, multi and bootstrap: one device after another."""
        results: list[StepResult] = []
        for i in range(len(self.doc["steps"])):
            why_not = self._why_not_start(i, results)
            if why_not:
                results.append(self._skip(i, why_not))
                continue
            try:
                step = self._input(i)
            except Exception as exc:  # noqa: BLE001 - e.g. a database error: this device fails, not the whole run
                res = _internal_error(exc)
            else:
                res = self._engine(i).run(step)
                if self.doc["kind"] == "bootstrap" and res.status == "success":
                    self._ssh_switch(i, res, step)
            self._store(i, res)
            results.append(res)
        return results

    def _why_not_start(self, i: int, results: list[StepResult]) -> str | None:
        if i == 0:
            return None
        if self.job_id in self.r.cancel_requests:
            return "Not started: the job was withdrawn."
        if self.doc.get("stop_on_failure", True) and results[-1].status != "success":
            return "Not started: an earlier device did not succeed (stop on failure)."
        login = self._login_key(i)
        for j, earlier in enumerate(results):
            if earlier.login_refused and self._login_key(j) == login:
                # Never keep trying a rejected login: with a shared TACACS/RADIUS account it would get locked.
                return (f"Not started: {self.doc['steps'][j]['device_name']} refused the login, so the same "
                        "login is not tried on more devices.")
        return None

    # -- building blocks
    def _login(self, i: int):
        return self.req.login_for(str(self.devices[i]["_id"]))

    def _login_key(self, i: int) -> tuple:
        """Identifies the login used for device i (compared in memory only, never stored)."""
        username, password, _ = self._login(i)
        return username, password.get_secret_value() if password else None

    def _params(self, i: int, driver, **override) -> ConnectParams:
        """How to reach device i: its inventory connection and this run's login, unless overridden."""
        device = self.devices[i]
        conn = device.get("connection", {})
        username, password, secret = self._login(i)
        values = {"method": conn.get("method"), "host": device.get("mgmt_ip"), "port": conn.get("port"),
                  "username": username, "password": password, "secret": secret,
                  "serial_port": conn.get("serial_port"), "baud": conn.get("baud") or 9600, **override}
        values["port"] = values["port"] or default_port(values["method"])
        return ConnectParams(device_type=driver.netmiko_device_type, config_prompt=driver.config_prompt, **values)

    def _input(self, i: int) -> StepInput:
        step, device = self.doc["steps"][i], self.devices[i]
        model = self.db.catalog_models.find_one({"_id": device["model_id"]})
        driver = get_driver(model["os_id"], ModelInfo.from_doc(model), self.r.settings)
        plan = validation.normalize_interfaces(merge_secrets(step.get("plan") or self.doc["plan"], self.req),
                                               driver.normalize_interface)
        return StepInput(driver=driver, plan=plan, params=self._params(i, driver), mgmt_ip=device.get("mgmt_ip"),
                         secrets=self.req.all_secrets())

    def _engine(self, i: int) -> PushEngine:
        def on_state(state: str) -> None:
            if not can_move(self.current[i], state):
                return
            now = clock.now()
            update = {"$set": {f"steps.{i}.status": state, "status": state, "updated_at": now},
                      "$push": {f"steps.{i}.timeline": {"state": state, "at": now}}}
            if state == "connecting":
                update["$set"][f"steps.{i}.started_at"] = now
            self.db.jobs.update_one({"_id": self._id}, update)
            self.current[i] = state

        return PushEngine(open_connection=lambda prm, notes: self.r.connector.open(prm, who=self.who, notes=notes),
                          on_state=on_state, cancelled=lambda: self.job_id in self.r.cancel_requests)

    def _skip(self, i: int, note: str) -> StepResult:
        res = StepResult(status=SKIPPED, notes=[note])
        self._store(i, res)
        return res

    def _store(self, i: int, res: StepResult) -> None:
        now = clock.now()
        p = f"steps.{i}."
        update = {"$set": {p + "status": res.status, p + "commands_sent": res.commands, p + "backup": res.backup,
                           p + "output": res.output, p + "checks": res.checks, p + "error": res.error,
                           p + "notes": res.notes, p + "mgmt_interface": res.mgmt_interface,
                           p + "finished_at": now, "updated_at": now},
                  "$push": {p + "timeline": {"state": res.status, "at": now}}}
        self.r._save(self._id, update)
        self.current[i] = res.status
        device = self.devices[i]
        if res.status != SKIPPED or res.output:
            self.db.devices.update_one({"_id": device["_id"]}, {"$set": {
                "status.reachable": res.status != "failed" or bool(res.backup),  # backup read = it answered
                "status.checked_at": now, "status.last_job": {"id": self.job_id, "status": res.status}}})

    def _finish(self, results: list[StepResult]) -> None:
        statuses = [r.status for r in results]
        status = aggregate(statuses)
        names = [s["device_name"] for s in self.doc["steps"]]
        if len(results) == 1:
            summary = None
        else:
            done = [n for n, s in zip(names, statuses, strict=True) if s == "success"]
            summary = f"{len(done)} of {len(results)} devices changed" + (f": {', '.join(done)}." if done else ".")
        now = clock.now()
        extra = {"cancel_reason": "withdrawn"} if status == "cancelled" else {}
        self.r._save(self._id, {"$set": {"status": status, "summary": summary, "finished_at": now, "updated_at": now,
                                         **extra}})
        rolled = "rolled_back" in statuses
        audit.record(self.db, f"job.{'rollback' if rolled else 'finish'}",
                     result="ok" if status == "success" else "failed", who=self.who,
                     target={"type": "job", "id": self.job_id},
                     details={"kind": self.doc["kind"], "status": status,
                              "steps": [{"device": n, "status": s, "commands_hash": st["commands_hash"],
                                         "error": r.error} for n, s, st, r in
                                        zip(names, statuses, self.doc["steps"], results, strict=True)]})

    # -- router link: both sides applied and verified, then both confirmed, then both saved
    def _link(self) -> list[StepResult]:
        a_name, b_name = (s["device_name"] for s in self.doc["steps"])
        engines = [self._engine(0), self._engine(1)]
        held: dict[int, Held] = {}
        results: list[StepResult | None] = [None, None]
        try:
            for i in (0, 1):
                out = engines[i].apply(self._input(i))
                if isinstance(out, StepResult):
                    results[i] = out
                    break
                held[i] = out
            if results[0] is not None:
                results[1] = self._skip(1, f"Not started: {a_name} was not changed, so the link is left "
                                           "untouched on both sides.")
            elif results[1] is not None:
                results[0] = engines[0].abort(held.pop(0), f"Rolled back because {b_name} failed, so the link "
                                                           "stays the same on both sides.")
            else:
                self._confirm_both(engines, held, results, a_name, b_name)
        except Exception as exc:  # noqa: BLE001 - e.g. a database error: never leave a side half-done
            for i in (0, 1):
                if i in held:
                    h = held.pop(i)
                    results[i] = engines[i].save(h) if h.confirmed else \
                        engines[i].abort(h, "Rolled back after an internal error.")
                elif results[i] is None:
                    results[i] = _internal_error(exc)
        for i in (0, 1):
            if self.current[i] not in TERMINAL:  # a skipped step is already stored
                self._store(i, results[i])
        return results

    @staticmethod
    def _confirm_both(engines: list[PushEngine], held: dict[int, Held], results: list, a_name: str,
                      b_name: str) -> None:
        """Both sides applied and verified. Each confirm cancels that device's revert timer; both are confirmed
        before either is saved, so the moment when one side is kept and the other may still revert is as short
        as possible. ``held``/``results`` are updated in place: _link's error handler reads them."""
        results[0] = engines[0].confirm(held[0])
        if results[0] is not None:  # A was not confirmed and reverts: roll B back too
            del held[0]
            results[1] = engines[1].abort(held.pop(1), f"Rolled back because {a_name} could not be confirmed, "
                                                       "so the link stays the same on both sides.")
            return
        results[1] = engines[1].confirm(held[1])
        if results[1] is not None:
            # B reverts by itself, but A is already confirmed: its timer is gone and no lab-tested command can
            # undo it. Do not save A, so its startup config still matches B's.
            del held[1]
            results[0] = engines[0].keep_unsaved(held.pop(0), (
                f"{b_name} was not confirmed and restores its old configuration, but {a_name} was already "
                f"confirmed, so the link is configured on {a_name} only. It was NOT saved on {a_name}: remove "
                f"the link configuration from {a_name} (or reload it), or fix {b_name} and run the link again."))
            return
        results[0] = engines[0].save(held.pop(0))
        results[1] = engines[1].save(held.pop(1))

    # -- bootstrap: prove SSH works before switching the device to it
    def _ssh_switch(self, i: int, res: StepResult, step: StepInput) -> None:
        """Runs after the setup was confirmed and saved: whatever happens here is recorded, never raised."""
        info = self.doc["bootstrap"] or {}
        device = self.devices[i]
        new_ip, admin = info.get("mgmt_ip"), info.get("admin_username")
        name = f"SSH login to {new_ip} as {admin}"
        notes: list[str] = []  # e.g. "host key stored" on this first SSH contact
        error = None
        try:
            params = self._params(i, step.driver, method="ssh", host=new_ip, port=22, username=admin,
                                  password=self.req.ssh_user_password, secret=self.req.new_enable_secret,
                                  serial_port=None)
            self.r.connector.open(params, who=self.who, notes=notes).close()
        except ConnectFailed as exc:
            error = exc.message
        except Exception as exc:  # noqa: BLE001
            error = f"Internal error ({type(exc).__name__})."
        res.notes += [n for n in notes if n not in res.notes]
        if error:
            res.checks.append({"name": name, "ok": False, "detail": error, "required": False})
            res.notes.append(f"The setup is saved, but the SSH test failed, so {device['name']} stays on its console "
                             "connection. Check the cabling / VLAN to the management network, then edit the device.")
            return
        res.checks.append({"name": name, "ok": True, "detail": "logged in", "required": False})
        try:
            self.db.devices.update_one({"_id": device["_id"]}, {"$set": {
                "mgmt_ip": new_ip, "connection": {"method": "ssh", "port": 22, "serial_port": None, "baud": None},
                "updated_at": clock.now()}})
        except DuplicateKeyError:
            res.notes.append(f"SSH works, but {new_ip} is now used by another device in the inventory; "
                             f"{device['name']} was not switched to SSH.")
            return
        except PyMongoError as exc:
            res.notes.append(f"SSH works, but the inventory could not be updated ({type(exc).__name__}); "
                             f"edit {device['name']} to use SSH to {new_ip}.")
            return
        res.notes.append(f"SSH works: {device['name']} now connects over SSH to {new_ip}.")
        audit.record(self.db, "device.update", who=self.who, target={"type": "device", "id": str(device["_id"])},
                     details={"by": "bootstrap", "job": self.job_id, "mgmt_ip": new_ip, "connection": "ssh"})


def _internal_error(exc: Exception) -> StepResult:
    log.error("job step crashed (%s)", type(exc).__name__)
    return StepResult(status="failed", error={"command": None, "message": f"Internal error ({type(exc).__name__})."})


# History list: the large per-step fields (running-config backups, transcripts) are not even read from MongoDB.
LIST_PROJECTION = {"plan": 0, "request": 0, **{f"steps.{k}": 0 for k in (
    "backup", "output", "commands", "commands_sent", "checks", "verify_commands", "plan")}}


def job_out(doc: dict, backup: bool = True) -> dict:
    """API view of a job. ``backup=False`` leaves out the running-config backups (viewer role)."""
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
    if not backup:
        for s in out.get("steps", []):
            s.pop("backup", None)
    return out
