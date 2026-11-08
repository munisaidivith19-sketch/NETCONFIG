# NetConfig Studio

A local web app for network engineers: pick a device (category → brand → series → model), fill in
your requirements (VLANs, ports, IP addressing, DHCP, NAT, routing, SSH), and NetConfig Studio validates
them, generates the right commands for that device's OS, shows a preview, pushes them safely with
backup and rollback, verifies the result, and records everything in an audit log.

It runs **on your own laptop, inside the network**, bound to `127.0.0.1`. It is not a cloud app.

> Status: under construction, built phase by phase from `PROMPTS.md`. See [Progress](#progress).

## Requirements (Windows 11, all free)
- Python 3.12 (3.10 works for now – see `docs/ACCEPTED_RISKS.md`)
- Node.js LTS (20+)
- MongoDB Community Server, running as a Windows service on `127.0.0.1:27017`
- Git

## First-time setup
```powershell
# 1. Backend: creates backend\.venv, installs pinned packages, creates backend\.env, starts the API
powershell -ExecutionPolicy Bypass -File scripts\dev-backend.ps1
# (stop it with Ctrl+C after it starts once)

# 2. Create the first admin (password is typed, never shown)
cd backend
.venv\Scripts\python scripts\create_user.py admin --role admin

# 3. Frontend
cd ..\frontend
npm ci
```
The sample catalog is loaded automatically on first start (or run `scripts\seed_catalog.py`).

## Run (development)
Two terminals:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev-backend.ps1   # API on http://127.0.0.1:8000
cd frontend; npm run dev                                          # UI  on http://127.0.0.1:5173
```
Open http://127.0.0.1:5173. Vite forwards `/api` to the backend, so the browser sees one origin.

## Run (production-style, one process)
```powershell
cd frontend; npm run build; cd ..\backend
$env:ENV="production"; .venv\Scripts\python -m app
```
Open http://127.0.0.1:8000 – FastAPI serves the built frontend. API docs (`/docs`) are off in production.

## Try a push without a device (simulation mode)
For demos and UI work only. Pushes go to an in-memory pretend Cisco switch, not the network, and a
yellow banner says so on every page. It is refused when `ENV=production`.
```powershell
cd backend
$env:SIMULATE_DEVICES="true"; .venv\Scripts\python -m app
```
Add a device (for example model *Cisco IOSvL2*, management IP `10.0.0.2`), then Configure → Preview →
Create job → enter any username and password (the password `wrong` simulates a login failure) → Run.
Real testing uses GNS3 / CML (`docs/LAB_TESTING.md`, Phase 3B).

## How a push works
1. **Create job** (Configure step 4): the exact commands are frozen with a SHA-256 hash. No credentials.
2. **Approval** (only devices tagged `production`): a *different* admin approves in History within 24 hours.
3. **Run**: the device login (and the password of a local user the plan creates) is typed now, sent once,
   kept in memory for this job only and wiped when it ends. The commands are regenerated and must match
   the approved hash.
4. **Push engine**: connect (SSH host key checked) → back up `show running-config` → find the interface
   that holds the management IP → denylist + management checks → apply inside
   `configure terminal revert timer N` → stop at the first CLI error → verify with `show` commands →
   `configure confirm` → `write memory`. Any error after applying → `configure revert now`; if the device
   is unreachable, its own timer restores the old config.
5. **History** shows the timeline, checks, the masked transcript and the masked backup.

The Cisco IOS driver is still **experimental** (not proven on an emulator yet). Lab devices can be pushed;
devices tagged `production` additionally need `ENABLE_EXPERIMENTAL_DRIVERS=true` until the driver is
marked `tested` (Phase 3B lab tests).

## Tests
```powershell
cd backend;  .venv\Scripts\python -m pytest          # needs MongoDB running (uses database netconfig_test)
cd frontend; npm test; npm run build
```
Golden files: `UPDATE_GOLDEN=1 .venv\Scripts\python -m pytest tests/drivers` rewrites
`tests/golden/<os_id>/*.txt`; review the diff before committing.

Static checks: `ruff check .`, `bandit -c pyproject.toml -r app scripts`, `pip-audit -r requirements.txt`, `npm audit`.

## Security in one minute
- **Localhost only** by default. `HOST` other than 127.0.0.1 needs `ALLOW_REMOTE=true` (and HTTPS).
- **Host allowlist** blocks DNS rebinding; **Origin + `X-Requested-With: NetConfigStudio`** blocks
  other websites from driving the API (CSRF to localhost). No CORS is ever answered.
- **Strict CSP** and security headers; no inline scripts.
- **Users and roles** (admin / engineer / viewer), bcrypt cost 12, 12+ character passwords,
  lockout after 5 failures for 15 minutes, server-side sessions (8 h absolute, 30 min idle).
- **Deny by default:** the app refuses to start if any API route has no role check.
- **Device passwords are never stored** – they are typed at push time and kept in memory for that job only.
- **SSH host keys are pinned** on first connection. If a device later offers a different key, the push stops
  before the password is sent, until an admin compares and accepts the new fingerprint (Admin → SSH host keys).
- **Two-person rule** for `production` devices, and **automatic rollback** (Cisco revert timer).
- **Audit log** is append-only with a hash chain, so edits or deletions are detectable.
- **No CLI injection:** every text field in a plan uses a character allowlist (no newline, `;`, `|`,
  `#`, `^`, `?`), so a hostname, description or banner can never start a second command. The final
  command list is also checked against a denylist (`reload`, `erase`, `do rel`, …) and against
  changes that would cut the management connection.

Details: `CLAUDE.md` section 8, `docs/adr/`, `docs/SYSTEM_DESIGN.md`, `docs/TEST_PLAN.md`.

## Project layout
```
backend/   FastAPI app (app/), tests/, scripts/
frontend/  React + Vite app (liquid-glass design: src/styles/tokens.css, app.css)
docs/      system design, ADRs, diagrams, test plan, drivers, lab testing, accepted risks
scripts/   Windows helper scripts
```

## Progress
| Phase | Part | Status |
|---|---|---|
| 1 | 1A architecture, ADRs, diagrams, test plan | done |
| 1 | 1B backend skeleton, security foundation, login UI | done |
| 1 | 1C catalog and device inventory | done |
| 1 | 1D review | done |
| 2 | 2A Cisco IOS research, 2B plan validation, Cisco driver, preview API, Configure wizard | done |
| 2 | 2C review | done |
| 3 | 3A safe push engine, approvals, live progress, History, SSH host keys | done |
| 3 | 3B console bootstrap, router link wizard, multi-device, templates | – |
| 3 | 3C review | – |
| 4 | Multi-vendor drivers, live dashboard, UI polish | – |
| 5 | AI assistant, hardening, docs, release | – |
