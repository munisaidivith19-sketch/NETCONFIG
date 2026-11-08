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

## Tests
```powershell
cd backend;  .venv\Scripts\python -m pytest          # needs MongoDB running (uses database netconfig_test)
cd frontend; npm test; npm run build
```
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
- **Audit log** is append-only with a hash chain, so edits or deletions are detectable.

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
| 2 | Configuration engine and Cisco IOS driver | next |
| 3 | Safe push engine, console bootstrap, multi-device | – |
| 4 | Multi-vendor drivers, live dashboard, UI polish | – |
| 5 | AI assistant, hardening, docs, release | – |
