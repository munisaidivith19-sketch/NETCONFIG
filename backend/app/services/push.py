"""Push engine for one device (docs/SYSTEM_DESIGN.md 5.3):

connecting → backing_up → checking → applying → verifying → (confirm) → saving → success
                              │           │            │
                              ▼           └── error / failed check / lost link ──► rolling_back
                           blocked                                                  ├► rolled_back
                                                                                    └► failed (MANUAL ACTION)

Nothing in a StepResult contains a secret: every text is masked and scrubbed of the known secret values.
The config is applied inside Cisco's "configure terminal revert timer N", so if this app crashes or the
link drops, the device restores its previous configuration by itself.
"""

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta

from pydantic import SecretStr

from .. import clock
from ..drivers.base import Check, Driver
from ..models.plan import ConfigPlan
from ..security.masking import MASK, mask_text
from . import safety
from .connection import ConnectFailed, Connection, ConnectionLost, ConnectParams

MANUAL = "MANUAL ACTION REQUIRED"
RSA_PROMPTS = [(r"\[yes/no\]", "yes")]
CONNECT_RETRY_SECONDS = 3  # one retry, timeouts only (never after a login failure: AAA lockout)


class Cancelled(Exception):
    pass


@dataclass
class StepInput:
    driver: Driver
    plan: ConfigPlan  # with real secrets (memory only)
    params: ConnectParams
    mgmt_ip: str | None
    secrets: list[SecretStr]  # every secret value of this run, scrubbed from all stored text


@dataclass
class StepResult:
    status: str
    commands: list[str] = field(default_factory=list)  # masked
    backup: str = ""
    output: str = ""
    checks: list[dict] = field(default_factory=list)
    error: dict | None = None
    notes: list[str] = field(default_factory=list)
    mgmt_interface: str | None = None


class Transcript:
    def __init__(self, secrets: list[SecretStr]):
        self._secrets = sorted({s.get_secret_value() for s in secrets if s and s.get_secret_value()}, key=len,
                               reverse=True)
        self.lines: list[str] = []

    def scrub(self, text: str) -> str:
        text = mask_text(text or "")
        for value in self._secrets:
            text = text.replace(value, MASK)
        return text

    def add(self, command: str, output: str = "") -> None:
        self.lines.append(self.scrub(f">>> {command}"))
        if output and output.strip():
            self.lines.append(self.scrub(output.rstrip()))

    def text(self) -> str:
        return "\n".join(self.lines)


def find_error(driver: Driver, output: str) -> str | None:
    """First output line that matches an error pattern and is not a known informational line."""
    info = [re.compile(p) for p in getattr(driver, "info_patterns", lambda: [])()]
    errors = [re.compile(p) for p in driver.error_patterns()]
    for line in (output or "").splitlines():
        if any(p.search(line) for p in info):
            continue
        if any(p.search(line) for p in errors):
            return line.strip()
    return None


def _has_archive(running_config: str) -> bool:
    in_archive = False
    for line in running_config.splitlines():
        if line.startswith("archive"):
            in_archive = True
        elif in_archive and line.startswith(" path "):
            return True
        elif line and not line.startswith(" "):
            in_archive = False
    return False


def _has_rsa_keys(output: str) -> bool:
    return bool(re.search(r"Key name:|Key Data:", output or ""))


class PushEngine:
    def __init__(self, open_connection: Callable[[ConnectParams, list[str]], Connection],
                 on_state: Callable[[str], None], cancelled: Callable[[], bool] = lambda: False,
                 sleep: Callable[[float], None] = time.sleep):
        self.open_connection = open_connection
        self.on_state = on_state
        self.cancelled = cancelled
        self.sleep = sleep

    def _connect(self, params: ConnectParams, notes: list[str]) -> Connection:
        try:
            return self.open_connection(params, notes)
        except ConnectFailed as exc:
            if exc.kind != "timeout":
                raise
            notes.append(f"The device did not answer; trying once more in {CONNECT_RETRY_SECONDS} seconds.")
            self.sleep(CONNECT_RETRY_SECONDS)
            return self.open_connection(params, notes)

    def _state(self, name: str, cancellable: bool = True) -> None:
        if cancellable and self.cancelled():
            raise Cancelled()
        self.on_state(name)

    def run(self, step: StepInput) -> StepResult:
        driver, plan = step.driver, step.plan
        plan_secrets = [plan.ssh.password, plan.ssh.enable_secret] if plan.ssh else []
        log = Transcript([*step.secrets, step.params.password, step.params.secret, *plan_secrets])
        res = StepResult(status="failed")
        conn: Connection | None = None
        applied = False  # True once the first config command may have reached the device
        try:
            self._state("connecting")
            try:
                conn = self._connect(step.params, res.notes)
            except ConnectFailed as exc:
                res.error = {"command": None, "message": exc.message}
                return res
            log.add("connected", "")

            self._state("backing_up")
            running = conn.show("show running-config")
            log.add("show running-config", f"({len(running.splitlines())} lines saved as backup)")
            res.backup = log.scrub(running)

            self._state("checking")
            mgmt_if = None
            via_ssh = step.params.method == "ssh"
            if step.mgmt_ip and step.params.method != "serial":
                brief = conn.show("show ip interface brief")
                log.add("show ip interface brief", brief)
                mgmt_if = driver.management_interface({"show ip interface brief": brief}, step.mgmt_ip)
                res.mgmt_interface = mgmt_if
                if mgmt_if is None:
                    res.status = "blocked"
                    res.error = {"command": None, "message": f"No interface holds the management address "
                                 f"{step.mgmt_ip}, so management protection cannot be checked. Nothing was sent."}
                    return res
                res.notes.append(f"Management interface: {mgmt_if} ({step.mgmt_ip}).")
            commands = driver.generate(plan, "push")
            if plan.ssh:
                keys = conn.show("show crypto key mypubkey rsa")
                log.add("show crypto key mypubkey rsa", "(key details hidden)")
                if _has_rsa_keys(keys) and not plan.ssh.regenerate_keys:
                    commands = [c for c in commands if not c.startswith("crypto key generate rsa")]
                    res.notes.append("RSA keys already exist; they are kept (plan did not ask to replace them).")
            res.commands = [log.scrub(c) for c in commands]
            violations = safety.check_denylist(commands) + safety.check_management(
                commands, mgmt_interface=mgmt_if, mgmt_ip=step.mgmt_ip, via_ssh=via_ssh,
                normalize_interface=driver.normalize_interface)
            if violations:
                v = violations[0]
                res.status = "blocked"
                res.error = {"command": log.scrub(v.command.strip()), "message": v.message.replace(v.command.strip(),
                             log.scrub(v.command.strip()))}
                return res

            strategy = driver.rollback_strategy()
            steps = driver.session_steps(plan)
            if strategy == "revert_timer" and not _has_archive(running):
                # Prerequisite for the timed rollback (docs/drivers/cisco_ios.md section 1).
                conn.enter_config("configure terminal")
                for line in steps["archive"]:
                    out = conn.config_line(line)
                    log.add(line, out)
                    if find_error(driver, out):
                        conn.exit_config()
                        res.error = {"command": line, "message": find_error(driver, out)}
                        return res
                conn.exit_config()
                res.notes.append("Configuration archive created (needed for the automatic rollback).")
            elif strategy != "revert_timer":
                raise NotImplementedError(f"rollback strategy {strategy}")  # Phase 4 drivers

            self._state("applying")  # last point where a cancel is honoured
            applied = True
            deadline = clock.now() + timedelta(minutes=plan.revert_minutes)
            begin = steps["begin"][0]
            log.add(begin, conn.enter_config(begin))
            res.notes.append(f"Automatic rollback armed: the device restores its old config at "
                             f"{deadline:%H:%M:%S} UTC unless the change is confirmed.")
            for cmd in commands:
                out = conn.config_line(cmd, RSA_PROMPTS if cmd.startswith("crypto key generate rsa") else None)
                log.add(cmd, out)
                err = find_error(driver, out)
                if err:
                    res.error = {"command": log.scrub(cmd), "message": log.scrub(err)}
                    conn.exit_config()
                    return self._rollback(conn, step, res, log, deadline)
            conn.exit_config()

            self.on_state("verifying")
            outputs = {}
            for cmd in driver.verify_commands(plan):
                outputs[cmd] = conn.show(cmd)
                log.add(cmd, outputs[cmd])
            checks = driver.check(plan, outputs)
            res.checks = [_check_out(c, log) for c in checks]
            failed = [c for c in checks if c.required and not c.ok]
            if failed:
                res.error = {"command": None, "message": f"Verification failed: {failed[0].name} ({failed[0].detail})"}
                return self._rollback(conn, step, res, log, deadline)

            out = conn.exec(steps["confirm"][0])
            log.add(steps["confirm"][0], out)
            if find_error(driver, out):
                res.error = {"command": steps["confirm"][0], "message": find_error(driver, out)}
                res.notes.append("The confirm failed, so the device will restore its old config when the timer ends.")
                res.status = "rolled_back"
                return res
            res.notes.append("Change confirmed; the rollback timer is cancelled.")

            save = driver.save_command()
            if plan.save and save:
                self.on_state("saving")
                out = conn.exec(save)
                log.add(save, out)
                if find_error(driver, out):
                    res.error = {"command": save, "message": find_error(driver, out)}
                    res.notes.append(f"{MANUAL}: the change is active but was NOT saved to the startup configuration.")
                    return res
            res.status = "success"
            return res
        except Cancelled:
            res.status = "cancelled"
            res.notes.append("Withdrawn before any configuration command was sent.")
            return res
        except ConnectionLost:
            if not applied:
                res.error = {"command": None, "message": "The connection was lost before anything was applied."}
                return res
            res.error = res.error or {"command": None,
                                      "message": "The connection to the device was lost after applying."}
            return self._rollback(None, step, res, log, None)
        except Exception as exc:  # noqa: BLE001 - never leak a stack trace; roll back if needed
            res.error = {"command": None, "message": f"Internal error ({type(exc).__name__})."}
            if applied:
                return self._rollback(conn, step, res, log, None)
            return res
        finally:
            res.output = log.text()
            if conn is not None:
                conn.close()

    def _rollback(self, conn: Connection | None, step: StepInput, res: StepResult, log: Transcript,
                  deadline) -> StepResult:
        self.on_state("rolling_back")
        revert = step.driver.session_steps(step.plan)["revert"][0]
        reopened: list[Connection] = []  # connections opened here are closed here; run() closes `conn`
        try:
            for attempt in ("current", "reconnect"):
                try:
                    if attempt == "reconnect" or conn is None:
                        conn = self.open_connection(step.params, res.notes)
                        reopened.append(conn)
                    out = conn.exec(revert)
                    log.add(revert, out)
                    refused = find_error(step.driver, out)
                    if refused:
                        res.status = "failed"
                        res.notes.append(f"{MANUAL}: '{revert}' was refused ({refused}). "
                                         "Check the device; its revert timer may still restore the old config.")
                        return res
                    res.status = "rolled_back"
                    res.notes.append("Rolled back: the previous configuration was restored.")
                    return res
                except (ConnectionLost, ConnectFailed):
                    continue
            # Could not reach the device: the revert timer on the device restores the config by itself.
            res.status = "rolled_back"
            when = f" at {deadline:%H:%M:%S} UTC" if deadline else ""
            res.notes.append(f"Device unreachable: it restores its previous configuration by its revert timer{when}. "
                             "Check it is reachable again afterwards.")
            return res
        finally:
            for c in reopened:
                c.close()


def _check_out(c: Check, log: Transcript) -> dict:
    return {"name": log.scrub(c.name), "ok": c.ok, "detail": log.scrub(c.detail), "required": c.required}
