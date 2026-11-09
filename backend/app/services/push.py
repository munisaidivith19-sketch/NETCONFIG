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
from datetime import datetime, timedelta

from pydantic import SecretStr

from .. import clock
from ..drivers.base import Check, Driver
from ..models.plan import ConfigPlan
from ..security.masking import MASK, mask_text
from . import safety
from .connection import ConnectFailed, Connection, ConnectionLost, ConnectParams

MANUAL = "MANUAL ACTION REQUIRED"
RSA_PROMPTS = [(r"\[yes/no\]", "yes")]
CONFIRM_MARGIN = timedelta(seconds=20)  # never confirm a change in its last seconds
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
    login_refused: bool = False  # the device rejected the login (not stored; stops retries on other devices)


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
    info = [re.compile(p) for p in driver.info_patterns()]
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


def _mentions(config: str, ip: str) -> bool:
    """Whether the address appears anywhere in the config as a whole address (not as part of a longer one)."""
    return re.search(rf"(?<![\d.]){re.escape(ip)}(?![\d.])", config or "") is not None


def _ssh_enabled(output: str) -> bool:
    """Whether SSH already runs, i.e. a usable RSA key pair exists. Counting key names in "show crypto key
    mypubkey rsa" is wrong: IOS-XE's TP-self-signed key (HTTP server) is listed there but never enables SSH."""
    return bool(re.search(r"SSH Enabled", output or ""))


@dataclass
class Held:
    """Applied and verified, not yet confirmed: the device's revert timer is still running."""

    conn: Connection
    step: StepInput
    res: StepResult
    log: Transcript
    deadline: datetime
    steps: dict
    confirmed: bool = False  # set by confirm(): the revert timer is cancelled, only the save is left


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
        """One device, start to finish: apply and verify, then confirm and save."""
        out = self.apply(step)
        return out if isinstance(out, StepResult) else self.commit(out)

    def apply(self, step: StepInput) -> "StepResult | Held":
        """Everything up to a verified change. Returns a Held step (still inside the revert timer, not yet
        confirmed) or a finished StepResult (blocked, failed, rolled back, cancelled)."""
        driver, plan = step.driver, step.plan
        plan_secrets = [plan.ssh.password, plan.ssh.enable_secret] if plan.ssh else []
        log = Transcript([*step.secrets, step.params.password, step.params.secret, *plan_secrets])
        res = StepResult(status="failed")
        conn: Connection | None = None
        applied = False  # True once the first config command may have reached the device
        held = None
        try:
            self._state("connecting")
            try:
                conn = self._connect(step.params, res.notes)
            except ConnectFailed as exc:
                res.error = {"command": None, "message": exc.message}
                res.login_refused = exc.kind == "auth"
                return res
            log.add("connected", "")

            self._state("backing_up")
            running = conn.show("show running-config")
            log.add("show running-config", f"({len(running.splitlines())} lines saved as backup)")
            res.backup = log.scrub(running)

            self._state("checking")
            mgmt_if = None
            via_ssh = step.params.method == "ssh"
            if step.mgmt_ip and step.params.method in ("ssh", "telnet_lab"):
                brief = conn.show("show ip interface brief")
                log.add("show ip interface brief", brief)
                mgmt_if = driver.management_interface({"show ip interface brief": brief}, step.mgmt_ip)
                res.mgmt_interface = mgmt_if
                # Over a lab console the address may be the console server (GNS3/CML), which no device port holds.
                # That is accepted only if the address appears nowhere in the device's config; otherwise the
                # interface list was simply not understood, and the push is blocked as it is over SSH.
                if mgmt_if is None and (via_ssh or _mentions(running, step.mgmt_ip)):
                    res.status = "blocked"
                    res.error = {"command": None, "message": f"No interface holds the management address "
                                 f"{step.mgmt_ip}, so management protection cannot be checked. Nothing was sent."}
                    return res
                if mgmt_if is None:
                    res.notes.append(f"{step.mgmt_ip} is not an address of the device, so this is a console-server "
                                     "connection; management-interface protection does not apply.")
                else:
                    res.notes.append(f"Management interface: {mgmt_if} ({step.mgmt_ip}).")
            commands = driver.generate(plan, "push")
            if plan.ssh:
                ssh_state = conn.show("show ip ssh")
                log.add("show ip ssh", ssh_state)
                if _ssh_enabled(ssh_state) and not plan.ssh.regenerate_keys:
                    commands = [c for c in commands if not c.startswith("crypto key generate rsa")]
                    res.notes.append("SSH already has RSA keys; they are kept (plan did not ask to replace them).")
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
                    err = find_error(driver, out)
                    if err:
                        conn.exit_config()
                        res.error = {"command": line, "message": err}
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
                # A whole config never goes into the transcript: viewers can read it, and they may not see
                # the backup either (job_out). The checks below report what was found in it.
                log.add(cmd, f"({len(outputs[cmd].splitlines())} lines read for verification)"
                        if cmd.startswith("show running-config") else outputs[cmd])
            checks = driver.check(plan, outputs)
            res.checks = [_check_out(c, log) for c in checks]
            failed = [c for c in checks if c.required and not c.ok]
            if failed:
                res.error = {"command": None, "message": f"Verification failed: {failed[0].name} ({failed[0].detail})"}
                return self._rollback(conn, step, res, log, deadline)
            held = Held(conn=conn, step=step, res=res, log=log, deadline=deadline, steps=steps)
            return held
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
            if held is None:
                res.output = log.text()
                if conn is not None:
                    conn.close()

    def commit(self, held: "Held") -> StepResult:
        """Confirm a verified change (this cancels the revert timer), then save it."""
        return self.confirm(held) or self.save(held)

    def confirm(self, held: "Held") -> StepResult | None:
        """Send the confirm. None = confirmed: the session stays open for save(). Otherwise the change was not
        confirmed (the device reverts by its timer, or was rolled back) and the finished StepResult is returned.
        A router link confirms both sides before saving either, so one side is never kept alone for long."""
        conn, step, res, log = held.conn, held.step, held.res, held.log
        try:
            if clock.now() >= held.deadline - CONFIRM_MARGIN:
                res.status = "rolled_back"
                res.error = {"command": None, "message": "The revert timer ran out before the change could be "
                             "confirmed; the device restored its previous configuration by itself."}
                return self._close(held)
            confirm = held.steps["confirm"][0]
            out = conn.exec(confirm)
            log.add(confirm, out)
            err = find_error(step.driver, out)
            if err:
                res.error = {"command": confirm, "message": err}
                res.notes.append("The confirm failed, so the device will restore its old config when the timer ends.")
                res.status = "rolled_back"
                return self._close(held)
            held.confirmed = True
            res.notes.append("Change confirmed; the rollback timer is cancelled.")
            return None
        except ConnectionLost:
            res.error = res.error or {"command": None, "message": "The connection was lost before the confirm."}
            return self._close(held, self._rollback(None, step, res, log, held.deadline))
        except Exception as exc:  # noqa: BLE001 - never leak a stack trace
            res.error = {"command": None, "message": f"Internal error ({type(exc).__name__})."}
            return self._close(held, self._rollback(conn, step, res, log, held.deadline))

    def save(self, held: "Held") -> StepResult:
        """Save a confirmed change to the startup configuration and close the session."""
        conn, step, res, log = held.conn, held.step, held.res, held.log
        try:
            save = step.driver.save_command()
            if step.plan.save and save:
                self.on_state("saving")
                out = conn.exec(save)
                log.add(save, out)
                err = find_error(step.driver, out)
                if err:
                    res.error = {"command": save, "message": err}
                    res.notes.append(f"{MANUAL}: the change is active but was NOT saved to the startup configuration.")
                    return res
            res.status = "success"
            return res
        except ConnectionLost:
            res.error = {"command": None, "message": "The connection was lost while saving."}
            res.notes.append(f"{MANUAL}: the change is active but may NOT be saved; check the device.")
            return res
        except Exception as exc:  # noqa: BLE001 - never leak a stack trace
            res.error = {"command": None, "message": f"Internal error ({type(exc).__name__})."}
            res.notes.append(f"{MANUAL}: the change is active; check whether it was saved.")
            return res
        finally:
            self._close(held)

    @staticmethod
    def _close(held: "Held", res: StepResult | None = None) -> StepResult:
        held.res.output = held.log.text()
        held.conn.close()
        return res or held.res

    def keep_unsaved(self, held: "Held", note: str) -> StepResult:
        """Close a confirmed change WITHOUT saving it. Used when the other side of a link could not be confirmed:
        a confirmed change has no revert timer left to undo it, so at least the startup configuration stays
        as it was (a reload restores the old config)."""
        held.res.status = "failed"
        held.res.error = held.res.error or {"command": None, "message": "Not saved: the other side of the link "
                                            "was not confirmed."}
        held.res.notes.append(f"{MANUAL}: {note}")
        return self._close(held)

    def abort(self, held: "Held", message: str) -> StepResult:
        """Roll back a verified but unconfirmed change (used when the other side of a link failed)."""
        held.res.error = held.res.error or {"command": None, "message": message}
        try:
            return self._rollback(held.conn, held.step, held.res, held.log, held.deadline)
        finally:
            self._close(held)

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
