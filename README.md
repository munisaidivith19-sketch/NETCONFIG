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
Real testing uses GNS3 / CML: follow `docs/LAB_TESTING.md`.

## Live overview (Phase 4B)
The **Overview** page is the home page. Everything on it comes from the backend (`GET /api/overview`):
- **Status check:** every `STATUS_POLL_SECONDS` (default 60, `0` turns it off) a background thread checks each
  device with a TCP connection to its SSH (or lab Telnet) port, or a ping when the device has no CLI port
  (access points, cameras). Results go to `devices.status` and a 14-day `status_samples` history.
  Engineers can press **Check status now**.
- **Read device facts:** select a device on the map and enter a device login. The app connects once (same host-key
  pinning as a push), runs only `show` commands, and stores the parsed model, version, serial, LLDP/CDP neighbours
  and VLAN table. The login is used once and never stored. If the device reports a different OS or model than the
  inventory says, a warning appears, because commands generated for the wrong OS would be wrong.
- **Map:** routers at the top, then Layer 3 switches, switches, and access points / cameras. Links come from
  LLDP/CDP and from access point uplinks. Neighbours not in the inventory are shown with a dashed border.
  Use the arrow keys to move between devices and Enter to select one.
- **Charts:** changes per day (14 days, succeeded vs failed or rolled back), reachable devices (24 h) and devices
  by category. Each chart has a **Show as table** button with the same numbers.

SNMPv3 polling is **not** built yet: it needs a new library (`pysnmp`), which needs the author's approval first.

## More than one device (Configure tabs)
- **Several switches** (Configure → Device change → *Several switches*): the same VLANs and port settings
  pushed to 2–20 switches one after another; by default it stops at the first switch that fails.
- **Router link**: pick two routers, their facing ports and a /30 or /31. Both sides get their address and
  matching OSPF / EIGRP / eBGP settings, and the two plans are checked to match before anything is sent.
  Both sides are applied and verified, then confirmed together; if one side fails, the other is rolled back.
  (One narrow exception: if B's confirm fails in the seconds after A's, A cannot be rolled back automatically.
  A is then **not saved**, and the job asks you to remove the link from A or reload it.)
- **First-time setup**: a new device over its serial console (USB cable, COMx) or a GNS3/CML lab console.
  Sets hostname, management address, gateway, admin user, enable secret, RSA keys, SSH v2 and SSH-only VTY
  lines, then tests an SSH login. Only if that works is the device switched to SSH.
- **Templates**: save the Configure form as a named template (never with passwords) and load it later.

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

## UI quality (Phase 4C)
Every page was reviewed in light and dark themes, at desktop and 375 px phone width. The full write-up is in
`docs/UI_REVIEW.md`.
- **Contrast:** computed to WCAG 2.1 AA in both themes. Seven light-theme token values were darkened.
- **Keyboard:** the network map and each chart are one Tab stop, moved with the arrow keys. Focus moves to
  each new wizard step, and charts have a "Show as table" option.
- **Phone:** the map and charts draw at the real panel width, so nodes and labels stay readable at 375 px.
- **Copy:** one word per concept ("job"). Safety warnings say what to do.
- **Rendered check:** the production build was loaded in headless Edge: 12 pages × 2 themes × 2 widths =
  48 views. All pass: no horizontal scroll, no console or CSP errors, every control at least 44 px.

## AI assistant (Phase 5A, optional)
Off by default. Set `AI_PROVIDER` in `backend\.env` to `ollama` (runs on this PC, free, no key), `groq` or
`gemini` (free tiers, need `AI_API_KEY`), then restart.
- **Describe what you need** (Configure → Requirements): a sentence becomes a plan draft that fills the form.
  The draft is validated, previewed, safety-checked and approved like any plan. It never includes SSH logins
  or custom commands, and nothing is pushed by the AI.
- **Explain** buttons: preview and job commands, a failed push, and "Compare with the previous backup" in a
  job.
- Texts are masked before they are sent, and device output is treated as untrusted (prompt injection).
  Engineers only, 10 requests per minute. Details: `docs/AI_ASSISTANT.md`.

## Tests
```powershell
cd backend;  .venv\Scripts\python -m pytest          # needs MongoDB running (uses database netconfig_test)
cd frontend; npm test; npm run build
```
Golden files: `UPDATE_GOLDEN=1 .venv\Scripts\python -m pytest tests/drivers` rewrites
`tests/golden/<os_id>/*.txt`; review the diff before committing.

Static checks: `ruff check .`, `bandit -c pyproject.toml -r app scripts`, `pip-audit -r requirements.txt`, `npm audit`.

## Security in one minute
- **Localhost only** by default. `HOST` other than 127.0.0.1 needs `ALLOW_REMOTE=true` **and**
  `SSL_CERTFILE`/`SSL_KEYFILE`: the app refuses to start without HTTPS.
- **Host allowlist** blocks DNS rebinding; **Origin + `X-Requested-With: NetConfigStudio`** blocks
  other websites from driving the API (CSRF to localhost). No CORS is ever answered.
- **Strict CSP** and security headers; no inline scripts.
- **Users and roles** (admin / engineer / viewer), bcrypt cost 12, 12+ character passwords,
  lockout after 5 failures for 15 minutes (atomic counter), server-side sessions (8 h absolute, 30 min idle).
- **Strict input:** unknown fields are rejected and types are strict (`"10"` is not a number).
- **Deny by default:** the app refuses to start if any API route has no role check.
- **Device passwords are never stored**: they are typed at push time and kept in memory for that job only.
  The browser is told not to save them either.
- **SSH host keys are pinned** on first connection. If a device later offers a different key, the push stops
  before the password is sent, until an admin compares and accepts the new fingerprint (Admin → SSH host keys).
- **Two-person rule** for `production` devices, and **automatic rollback** (Cisco revert timer).
  A job runs only against the address and connection method it was previewed (and approved) for, and only
  an admin can change the address, connection or model of a `production` device.
- **Custom commands** may not contain passwords, keys or SNMP communities (they are stored in the job record).
- **Audit log** is append-only with a hash chain, so edits or deletions are detectable.
- **No CLI injection:** every text field in a plan uses a character allowlist (no newline, `;`, `|`,
  `#`, `^`, `?`), so a hostname, description or banner can never start a second command. The final
  command list is also checked against a denylist (`reload`, `erase`, `do rel`, …) and against
  changes that would cut the management connection.

Details: **`docs/SECURITY.md`** (STRIDE threat model, CLAUDE.md §8 compliance table, limitations),
**`docs/SECURITY_TESTING.md`** (how to demo each control), `docs/adr/`, `docs/TEST_PLAN.md`.

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
| 3 | 3B console bootstrap, router link wizard, multi-device, templates | done (lab checklist in `docs/LAB_TESTING.md` not run yet) |
| 3 | 3C review (code review, simplify, security review) | done |
| 4 | 4A Arista, Juniper, Aruba drivers; experimental MikroTik, Huawei, D-Link, TP-Link; APs and cameras | done (all drivers experimental until `docs/LAB_TESTING.md` Part B passes) |
| 4 | 4B status polling, read-only discovery, topology, live Overview | done (SNMPv3 not built: needs approval for `pysnmp`) |
| 4 | 4C UI quality pass (contrast, keyboard, phone width, copy; see `docs/UI_REVIEW.md`) | done |
| 4 | 4D review | done |
| 5 | 5A AI assistant (Ollama / Groq / Gemini; draft + explain) | done (not yet tried against a live provider) |
| 5 | 5B security hardening (§8 review, HTTPS for remote mode, strict types, STRIDE docs) | done |
| 5 | 5C clean-up, docs and release | – |
