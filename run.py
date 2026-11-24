"""Run the whole of NetConfig Studio with one command, with clear errors.

    python run.py               daily use: production mode, one server, opens the browser
    python run.py --demo        demo: pushes go to a simulated device (no lab needed)
    python run.py --dev         development: backend auto-reload + Vite dev server
    python run.py --test        run the backend and frontend tests
    python run.py --no-browser  (with any mode) do not open the browser

It does the setup on its own when needed: creates backend\\.venv, installs the pinned packages,
creates backend\\.env, checks MongoDB, offers to create the first admin, installs and builds the
frontend. Each step prints OK or FAIL; on a failure it shows what went wrong, the last lines of
output and how to fix it. Standard library only, so it runs before anything is installed.
"""

import argparse
import collections
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess  # nosec B404 - runs fixed project commands, never shell=True
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
VENV_PY = BACKEND / ".venv" / "Scripts" / "python.exe" if os.name == "nt" else BACKEND / ".venv" / "bin" / "python"
REQ_MARKER = BACKEND / ".venv" / ".netconfig-requirements.sha256"
DEV_UI_PORT = 5173

os.system("")  # noqa: S605 S607  # nosec B605 B607 - constant empty command: turns on ANSI colours in the console
RED, GREEN, YELLOW, CYAN, BOLD, RESET = "\033[91m", "\033[92m", "\033[93m", "\033[96m", "\033[1m", "\033[0m"

# Known error text -> what to do about it. Checked against the output of the step that failed.
HINTS = [
    (r"10048|address already in use|only one usage of each socket address",
     "The port is already used, probably by NetConfig Studio still running in another window. Close it, "
     "or set another PORT in backend\\.env."),
    (r"ServerSelectionTimeout|27017|MongoDB not reachable|Connection refused",
     "MongoDB is not running. Start it: Services app -> MongoDB -> Start, or in an admin PowerShell: "
     "Start-Service MongoDB"),
    (r"Refusing to bind",
     "HOST in backend\\.env is not 127.0.0.1. Set HOST=127.0.0.1 (remote mode needs ALLOW_REMOTE=true and HTTPS)."),
    (r"HTTPS needs both|HTTPS file not found",
     "SSL_CERTFILE / SSL_KEYFILE in backend\\.env: set both to existing files, or leave both empty."),
    (r"SIMULATE_DEVICES=true is not allowed",
     "The simulator only runs in development: use  python run.py --demo"),
    (r"ModuleNotFoundError|No module named",
     "A Python package is missing. Delete backend\\.venv\\.netconfig-requirements.sha256 and run again "
     "(it reinstalls the packages)."),
    (r"Could not find a version|NewConnectionError|Failed to establish|getaddrinfo|ENOTFOUND|ETIMEDOUT",
     "No internet connection (needed once, to download packages). Connect and run again."),
    (r"validation error for Settings|Input should be",
     "A value in backend\\.env has the wrong format (see the field name above). Compare it with .env.example."),
    (r"Password does not meet the policy|must not contain the username|at least 12",
     "Choose a password with at least 12 characters that does not contain the user name."),
    (r"npm ERR!|ERESOLVE|EPERM|EBUSY",
     "npm failed. Close editors or servers using frontend\\node_modules, delete that folder and run again."),
]


# ---------------------------------------------------------------- output helpers
class StepFailed(Exception):
    def __init__(self, message, output="", hint=None):
        super().__init__(message)
        self.output, self.hint = output, hint


def info(text):
    print(f"      {text}")


def step(number, total, text):
    print(f"{CYAN}[{number}/{total}]{RESET} {text} ... ", end="", flush=True)


def ok(note=""):
    print(f"{GREEN}OK{RESET}" + (f"  {note}" if note else ""))


def mask(text):
    """Hide a password in a mongodb://user:password@host URI before it is printed."""
    return re.sub(r"//[^/@\s]+@", "//***@", text)


def hint_for(text):
    return next((h for pattern, h in HINTS if re.search(pattern, text, re.IGNORECASE)), None)


def error_box(title, message, output="", hint=None):
    line = "=" * 78
    print(f"\n{RED}{line}\n  ERROR: {title}\n{line}{RESET}")
    print(f"{BOLD}{mask(message)}{RESET}")
    tail = [x for x in mask(output or "").splitlines() if x.strip()][-30:]
    if tail:
        print(f"\n{YELLOW}Last lines of output:{RESET}")
        for x in tail:
            print(f"  | {x}")
    hint = hint or hint_for((output or "") + "\n" + message)
    if hint:
        print(f"\n{GREEN}How to fix:{RESET} {hint}")
    print(f"{RED}{line}{RESET}\n")


def run(cmd, cwd, env=None, timeout=None):
    """Run a setup command, capture its output; raise StepFailed with that output if it fails."""
    try:
        result = subprocess.run([str(c) for c in cmd], cwd=cwd, env=env, capture_output=True, text=True,  # noqa: S603  # nosec B603
                                encoding="utf-8", errors="replace", timeout=timeout)
    except FileNotFoundError as exc:
        raise StepFailed(f"Program not found: {cmd[0]}", str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise StepFailed(f"Timed out after {timeout} s: {' '.join(map(str, cmd))}", str(exc.output or "")) from exc
    if result.returncode != 0:
        raise StepFailed(f"Command failed (exit code {result.returncode}): {' '.join(map(str, cmd))}",
                         (result.stdout or "") + "\n" + (result.stderr or ""))
    return result.stdout


def port_open(host, port):
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def child_env(mode):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    if mode == "production":
        env["ENV"] = "production"
        env["SIMULATE_DEVICES"] = "false"  # beats a SIMULATE_DEVICES=true left in backend\.env
    else:
        env["ENV"] = "development"
        env["SIMULATE_DEVICES"] = "true" if mode == "demo" else env.get("SIMULATE_DEVICES", "false")
    return env


# ---------------------------------------------------------------- setup steps
def check_python():
    if sys.version_info < (3, 10):  # noqa: UP036 - this launcher may be started by an older Python
        raise StepFailed(f"Python 3.10 or newer is needed, this is {sys.version.split()[0]}.",
                         hint="Install Python 3.12 from python.org and run:  py -3.12 run.py")
    return sys.version.split()[0]


def find_npm():
    npm = shutil.which("npm")
    if not npm:
        raise StepFailed("Node.js / npm not found.",
                         hint="Install Node.js LTS from nodejs.org, then open a new terminal and run again.")
    return npm


def ensure_venv():
    if VENV_PY.exists():
        return "exists"
    candidates = []
    if shutil.which("py"):
        candidates += [["py", "-3.12"], ["py", "-3.10"]]
    candidates.append([sys.executable])
    for base in candidates:
        try:
            run(base + ["-c", "import sys; assert sys.version_info >= (3, 10)"], ROOT, timeout=60)
        except StepFailed:
            continue
        run(base + ["-m", "venv", str(BACKEND / ".venv")], BACKEND, timeout=300)
        return "created with " + " ".join(base)
    raise StepFailed("Could not create backend\\.venv: no Python 3.12 or 3.10 found.",
                     hint="Install Python 3.12 from python.org (tick 'Add python.exe to PATH').")


def ensure_packages():
    requirements = BACKEND / "requirements.txt"
    digest = hashlib.sha256(requirements.read_bytes()).hexdigest()
    if REQ_MARKER.exists() and REQ_MARKER.read_text().strip() == digest:
        return "up to date"
    run([VENV_PY, "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", requirements],
        BACKEND, timeout=1800)
    REQ_MARKER.write_text(digest)
    return "installed from requirements.txt"


def ensure_env_file():
    env_file = BACKEND / ".env"
    if env_file.exists():
        return "exists"
    shutil.copyfile(BACKEND / ".env.example", env_file)
    return "created from .env.example"


PROBE = r"""
import json
from app.config import Settings
out = {}
try:
    s = Settings()
    out.update(host=s.host, port=s.port, https=s.https, mongo_db=s.mongo_db)
    s.check_bind_address()
    s.check_simulation()
except Exception as exc:
    out["settings_error"] = f"{type(exc).__name__}: {exc}"
    print(json.dumps(out)); raise SystemExit
try:
    from pymongo import MongoClient
    client = MongoClient(s.mongo_uri, serverSelectionTimeoutMS=2500)
    client.admin.command("ping")
    out["users"] = client[s.mongo_db].users.count_documents({})
except Exception as exc:
    out["mongo_error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
print(json.dumps(out))
"""


def probe(env):
    text = run([VENV_PY, "-c", PROBE], BACKEND, env=env, timeout=60)
    try:
        return json.loads(text.strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise StepFailed("Could not read the app settings.", text) from exc


CREATE_ADMIN = "cd backend; .venv\\Scripts\\python scripts\\create_user.py admin --role admin"


def create_first_admin():
    """Returns the new admin's name, or None when this terminal cannot ask (the app still starts)."""
    print(f"\n{YELLOW}No user exists yet, so nobody can sign in. Create the first admin account now.{RESET}")
    try:
        if not sys.stdin.isatty():
            raise EOFError
        name = input("      Admin user name [admin]: ").strip() or "admin"
    except EOFError:
        print(f"{YELLOW}      This terminal cannot ask for a password. Later, in a normal terminal, run:{RESET}\n"
              f"        {CREATE_ADMIN}")
        return None
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", name):
        raise StepFailed("User names may only use letters, digits, _ . and -.")
    # Interactive (getpass asks for the password); output goes straight to this terminal.
    result = subprocess.run([str(VENV_PY), "scripts/create_user.py", name, "--role", "admin"], cwd=BACKEND)  # noqa: S603  # nosec B603
    if result.returncode != 0:
        raise StepFailed("Creating the admin account failed (see the message above).",
                         hint="Choose a password with at least 12 characters that does not contain the user name.")
    return name


def newest_source_time():
    files = [p for p in (FRONTEND / "src").rglob("*") if p.is_file()]
    files += [FRONTEND / n for n in ("index.html", "package-lock.json", "vite.config.js") if (FRONTEND / n).exists()]
    return max(p.stat().st_mtime for p in files)


def ensure_node_modules(npm):
    marker = FRONTEND / "node_modules" / ".package-lock.json"
    lock = FRONTEND / "package-lock.json"
    if marker.exists() and marker.stat().st_mtime >= lock.stat().st_mtime:
        return "up to date"
    run([npm, "ci", "--no-audit", "--no-fund"], FRONTEND, timeout=1800)
    return "installed (npm ci)"


def ensure_build(npm):
    index = FRONTEND / "dist" / "index.html"
    if index.exists() and index.stat().st_mtime >= newest_source_time():
        return "up to date"
    run([npm, "run", "build"], FRONTEND, timeout=600)
    return "built frontend\\dist"


# ---------------------------------------------------------------- running servers
class Server:
    """A child process whose output is shown live and whose last lines are kept for the error box."""

    def __init__(self, name, cmd, cwd, env, prefix=""):
        self.name, self.prefix = name, prefix
        self.tail = collections.deque(maxlen=60)
        self.proc = subprocess.Popen([str(c) for c in cmd], cwd=cwd, env=env, stdout=subprocess.PIPE,  # noqa: S603  # nosec B603
                                     stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        for line in self.proc.stdout:
            line = line.rstrip()
            self.tail.append(line)
            colour = RED if re.search(r"\b(ERROR|CRITICAL|Traceback)\b", line) else ""
            print(f"{self.prefix}{colour}{line}{RESET if colour else ''}", flush=True)

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def announce_when_ready(host, port, url, open_browser, servers):
    for _ in range(120):
        if any(s.proc.poll() is not None for s in servers):
            return
        if port_open(host, port):
            print(f"\n{GREEN}{BOLD}  NetConfig Studio is running:  {url}{RESET}   (Ctrl+C to stop)\n", flush=True)
            if open_browser:
                webbrowser.open(url)
            return
        time.sleep(0.5)
    print(f"{YELLOW}The server has not answered on {host}:{port} after 60 s; see its output above.{RESET}")


def serve(servers, host, port, url, open_browser):
    threading.Thread(target=announce_when_ready, args=(host, port, url, open_browser, servers), daemon=True).start()
    try:
        while True:
            for s in servers:
                code = s.proc.poll()
                if code is not None:
                    for other in servers:
                        other.stop()
                    time.sleep(0.3)  # let the output thread print the last lines
                    if code != 0:
                        error_box(f"{s.name} stopped unexpectedly (exit code {code})",
                                  f"The {s.name} process ended. The reason is in the lines below.",
                                  "\n".join(s.tail))
                        return 1
                    print(f"{s.name} stopped.")
                    return 0
            time.sleep(0.5)
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Stopping...{RESET}")
        for s in servers:
            s.stop()
        print("Stopped.")
        return 0


def run_tests(npm, env):
    print(f"\n{CYAN}== Backend tests (pytest){RESET}")
    env = dict(env, REQUIRE_MONGO="1", ENV="test")
    results = {
        "backend tests": subprocess.run([str(VENV_PY), "-m", "pytest", "-q", "-p", "no:warnings"],  # noqa: S603  # nosec B603
                                        cwd=BACKEND, env=env).returncode,
    }
    print(f"\n{CYAN}== Frontend tests (vitest){RESET}")
    results["frontend tests"] = subprocess.run([npm, "test"], cwd=FRONTEND).returncode  # noqa: S603  # nosec B603
    print(f"\n{CYAN}== Summary{RESET}")
    for name, code in results.items():
        print(f"  {GREEN + 'PASS' if code == 0 else RED + 'FAIL'}{RESET}  {name}")
    if any(results.values()):
        error_box("Some tests failed", "Scroll up to the first FAILED line to see which test and why.")
        return 1
    return 0


# ---------------------------------------------------------------- main
def main():
    parser = argparse.ArgumentParser(description="Run NetConfig Studio.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--demo", action="store_true", help="simulated devices (development mode)")
    group.add_argument("--dev", action="store_true", help="backend auto-reload + Vite dev server")
    group.add_argument("--test", action="store_true", help="run the backend and frontend tests")
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser")
    args = parser.parse_args()
    mode = "demo" if args.demo else "dev" if args.dev else "test" if args.test else "production"
    env = child_env(mode)

    print(f"{BOLD}NetConfig Studio{RESET} - mode: {mode}\n")
    total = 8
    current = "start"
    try:
        current = "Python"
        step(1, total, current)
        ok(check_python())
        current = "Node.js / npm"
        step(2, total, current)
        npm = find_npm()
        ok("npm " + run([npm, "--version"], ROOT, timeout=60).strip())
        current = "Backend virtual environment (backend\\.venv)"
        step(3, total, current)
        ok(ensure_venv())
        current = "Backend packages"
        step(4, total, current)
        ok(ensure_packages())
        current = "Settings file (backend\\.env)"
        step(5, total, current)
        note = ensure_env_file()
        state = probe(env)
        if "settings_error" in state:
            raise StepFailed("backend\\.env has a problem.", state["settings_error"])
        ok(f"{note}; {'https' if state['https'] else 'http'}://{state['host']}:{state['port']}")
        current = "MongoDB"
        step(6, total, current)
        if "mongo_error" in state:
            raise StepFailed("MongoDB is not reachable.", state["mongo_error"],
                             hint="Start MongoDB: Services app -> MongoDB -> Start, or in an admin PowerShell: "
                                  "Start-Service MongoDB. Not installed? Get MongoDB Community Server (free) "
                                  "from mongodb.com.")
        ok(f"database '{state['mongo_db']}', {state['users']} user(s)")
        if state["users"] == 0 and mode != "test":
            name = create_first_admin()
            if name:
                info(f"first admin created: {name}")
        current = "Frontend packages (node_modules)"
        step(7, total, current)
        ok(ensure_node_modules(npm))
        current = "Frontend build" if mode in ("production", "demo") else "Ports"
        step(8, total, current)
        if mode in ("production", "demo"):
            ok(ensure_build(npm))
        else:
            ok("not needed for this mode")
    except StepFailed as exc:
        print(f"{RED}FAIL{RESET}")
        error_box(f"step '{current}' failed", str(exc), exc.output, exc.hint)
        return 1
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Cancelled.{RESET}")
        return 1

    if mode == "test":
        return run_tests(npm, env)

    host, port = state["host"], state["port"]
    busy = [p for p in ([port, DEV_UI_PORT] if mode == "dev" else [port]) if port_open(host, p)]
    if busy:
        error_box("port already in use", f"Something is already listening on {host}:{busy[0]}.",
                  hint="NetConfig Studio is probably still running in another window: close it (Ctrl+C) "
                       "and run again, or set another PORT in backend\\.env.")
        return 1

    scheme = "https" if state["https"] else "http"
    url_host = f"[{host}]" if ":" in host else host
    if mode == "dev":
        servers = [Server("backend", [VENV_PY, "-m", "app", "--reload"], BACKEND, env, prefix=f"{CYAN}[api]{RESET} "),
                   Server("frontend dev server", [npm, "run", "dev"], FRONTEND, env, prefix=f"{GREEN}[ui]{RESET}  ")]
        return serve(servers, "127.0.0.1", DEV_UI_PORT, f"http://127.0.0.1:{DEV_UI_PORT}/", not args.no_browser)
    if mode == "demo":
        print(f"{YELLOW}Demo mode: pushes go to a simulated device, not the network.{RESET}")
    servers = [Server("backend", [VENV_PY, "-m", "app"], BACKEND, env)]
    return serve(servers, host, port, f"{scheme}://{url_host}:{port}/", not args.no_browser)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - last resort: never end with a raw traceback
        import traceback

        error_box("unexpected error in run.py", f"{type(exc).__name__}: {exc}", traceback.format_exc(),
                  hint="This is a bug in run.py itself. Copy this box when you report it.")
        sys.exit(1)
