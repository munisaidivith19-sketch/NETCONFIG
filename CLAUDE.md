# NetConfig Studio – Multi-Vendor Network Configuration Platform

> Project brief for Claude Code. Keep this file in the project root as `CLAUDE.md`.
> Claude Code reads it automatically at the start of every session.

## 1. Problem statement
Network engineers configure switches, Layer 3 switches, routers and access points one command at a
time in PuTTY. Every brand uses different commands (Cisco IOS, Junos, AOS-CX…), mistakes cause
outages, first-time SSH setup needs a console cable, and nobody records what was changed.
NetConfig Studio lets an engineer pick a device (category → brand → series → model), enter
requirements in a form (VLANs, access/trunk ports, IPs, DHCP, NAT, OSPF/EIGRP/BGP, SSH), and the
platform validates them, generates the correct commands for that device's OS, shows a preview,
pushes them safely, verifies the result with `show` commands, and records everything.

## 2. Architecture (do not change without asking)
```
Engineer's browser ──► FastAPI app on the engineer's laptop (127.0.0.1 only)
                         ├── serves the built React frontend (same origin)
                         ├── REST API /api/*
                         ├── Driver layer (one driver per OS family) ──► Netmiko ──► devices
                         │        SSH (normal) · serial console / lab console (first-time setup)
                         └── MongoDB (local) – catalog, inventory, jobs, backups, audit log
```
- The app runs **inside the network** on the engineer's PC, because it must reach the devices.
  It is not a cloud app. It binds to `127.0.0.1` by default.
- PuTTY is **not** automated. Netmiko does the same job (SSH / Telnet / serial) in code.
- Commands depend on the **OS family, not the model**. Models are catalog data that point to a driver.

## 3. Tech stack and constraints
- **Backend:** Python 3.12, FastAPI, Pydantic v2, Uvicorn, Netmiko, pyserial, PyMongo (sync client is
  fine – Netmiko is synchronous), pytest. Background push jobs in a thread pool.
- **Frontend:** React + Vite + React Router, **plain CSS** with CSS variables, lucide-react icons,
  `@fontsource-variable/inter` and `jetbrains-mono`. No UI framework, no Tailwind.
- **Database:** local MongoDB Community Server (`mongodb://127.0.0.1:27017`, database `netconfig`).
- **No Docker. Free tools only. Must run natively on Windows 11.** Use a `.venv` in `backend/`.
- **Lab for testing:** GNS3 / Cisco CML-Free (IOSv, IOSvL2), Juniper vJunos-switch/router,
  Arista cEOS-lab, Aruba AOS-CX Simulator, MikroTik CHR.

## 4. Folder structure
```
netconfig-studio/
├── CLAUDE.md
├── README.md
├── backend/
│   ├── app/
│   │   ├── main.py              # app factory, middleware, static frontend, lifespan
│   │   ├── config.py            # settings from environment
│   │   ├── db.py                # MongoDB client + indexes
│   │   ├── security/            # localhost guard, sessions, CSRF, RBAC, rate limit, masking
│   │   ├── models/              # Pydantic models: catalog, device, plan, job, user
│   │   ├── api/                 # routers: auth, catalog, devices, plans, jobs, audit, health
│   │   ├── drivers/
│   │   │   ├── base.py          # Driver interface
│   │   │   ├── registry.py      # os_id → driver
│   │   │   ├── cisco_ios.py  arista_eos.py  juniper_junos.py  aruba_aoscx.py
│   │   │   └── experimental/    # mikrotik, huawei_vrp, dlink, tplink (disabled by default)
│   │   ├── services/
│   │   │   ├── validation.py    # cross-field checks (ipaddress module)
│   │   │   ├── safety.py        # denylist, management-interface protection
│   │   │   ├── push.py          # connect → backup → checks → apply → verify → save/rollback
│   │   │   ├── jobs.py          # background job runner + progress
│   │   │   └── audit.py
│   │   └── data/catalog.json    # seed catalog (brands, series, models, os drivers)
│   ├── tests/                   # unit tests + golden command files per driver
│   ├── scripts/                 # seed_catalog.py, import_netbox_devicetypes.py, create_user.py
│   ├── requirements.txt
│   └── .env.example
├── frontend/                    # React app (already built – keep its design system)
│   └── src/ (components, pages, lib, data, styles)
├── lab/                         # GNS3/CML topology notes and starting configs
└── docs/                        # architecture, drivers, security, lab testing, user guide
```

## 5. The existing frontend (keep it)
`frontend/` already contains the full UI on demo data: Overview (topology map, device panel,
KPIs, charts), Devices, Configure (5-step wizard), Catalog and History.
- **Keep the design system** in `src/styles/tokens.css` and `src/styles/app.css`: light
  "liquid glass" theme (frosted panels with `backdrop-filter`, top-edge sheen, radii 18–32 px,
  soft layered shadows, green accent), dark theme, 44 px touch targets, visible focus, reduced
  motion, works down to 375 px with a bottom nav on mobile.
- Components must use tokens (CSS variables), never raw colours.
- `src/lib/commands.js` and `validate.js` are **preview only**. The backend is the source of truth:
  the frontend must request previews from the API once the backend exists.
- If `frontend/` is missing, rebuild it with the same pages and design rules.

## 6. Domain model
- **Category:** switch, l3switch, router, ap, camera, unmanaged.
- **Catalog:** Brand → Series (category, os_id) → Model (ports, uplinks, PoE, layer, port_prefix,
  port naming, capabilities). Seed from `catalog.json`; optional import script for the NetBox
  community device-type library (check its licence). Mark sample data as unverified.
- **OS driver** (`os_id`): name, support level (`tested | experimental | planned | inventory`),
  connection types, apply mode (immediate / commit), save command, Netmiko `device_type`,
  capability matrix (vlans, access, trunk, svi, routed_if, dhcp, nat, static, ospf, eigrp, bgp, ssh).
- **Device (inventory):** name, model ref, os_id, management IP, connection method, location, status.
  **Never stores device passwords.**
- **ConfigPlan:** basic (hostname, domain), ssh, hardening, vlans, access ports, trunks, svis,
  routed interfaces, dhcp pools, nat, static routes, routing (ospf/eigrp/bgp), save flag.
- **Job:** device, plan (secrets removed), generated commands (masked), status
  (`awaiting_approval, ready, queued, connecting, backing_up, checking, applying, verifying, saving,
  rolling_back, success, failed, rolled_back, blocked, cancelled, expired`), per-step timestamps,
  device output (masked), verification checks, backup config (masked), user, created_at.
  - `awaiting_approval`: production device, waiting for a second user. Becomes `expired` if not
    approved within 24 hours.
  - `ready`: approved (or no approval needed); waiting for the engineer to run it.
  - `cancelled`: rejected by the approver or withdrawn by the requester before applying.
  - Device credentials are entered **only after approval** (when the job is run), never while it waits.

## 7. Driver interface (every OS driver implements this)
```python
class Driver(Protocol):
    os_id: str
    netmiko_device_type: str          # e.g. "cisco_ios", "juniper_junos", "aruba_aoscx", "arista_eos"
    capabilities: set[str]
    def generate(self, plan: ConfigPlan, kind: str) -> list[str]: ...        # config commands
    def verify_commands(self, plan: ConfigPlan) -> list[str]: ...            # show commands
    def check(self, plan: ConfigPlan, outputs: dict[str, str]) -> list[Check]: ...
    def error_patterns(self) -> list[str]: ...                               # "% Invalid input" …
    def save_command(self) -> str | None: ...
    def rollback_strategy(self) -> str: ...  # "revert_timer" | "commit_confirmed" | "backup_restore"
    def management_interface(self, outputs: dict[str, str], mgmt_ip: str) -> str | None: ...
```
- Generators are **pure functions** (no device access) with golden-file tests
  (`tests/golden/<os_id>/<case>.txt`).
- A plan feature the driver does not support → clear "not supported on <OS>" error, never silent skip.
- Experimental drivers are disabled unless `ENABLE_EXPERIMENTAL_DRIVERS=true` and are labelled in the UI.

## 8. SECURITY REQUIREMENTS (mandatory in every phase)
This is a network security project. If a request conflicts with these rules, stop and ask.

### 8.1 Local app protection
- Bind to `127.0.0.1` by default. Binding to another address requires `ALLOW_REMOTE=true`,
  HTTPS and login, and shows a warning on startup.
- **Host header allowlist** (`127.0.0.1:<port>`, `localhost:<port>`) to block DNS-rebinding.
- **Origin check** on every state-changing request + required custom header
  (`X-Requested-With: NetConfigStudio`) so other websites cannot drive the API (CSRF to localhost).
- No CORS middleware in production (same origin). Dev: allow only the Vite origin.
- Security headers: CSP (`default-src 'self'`; no inline scripts), `X-Content-Type-Options`,
  `X-Frame-Options: DENY` / `frame-ancestors 'none'`, `Referrer-Policy: no-referrer`.
- `/docs` and `/openapi.json` disabled when `ENV=production`.

### 8.2 Users and roles
- Local login: bcrypt (cost ≥ 12), min 12-character passwords, lockout after 5 failures for 15 min.
- Sessions in httpOnly, SameSite=Strict cookies, stored server-side with TTL (8 h absolute, 30 min idle).
- Roles: `admin` (users, settings, approve), `engineer` (create plans, push to lab devices,
  request production pushes), `viewer` (read only). Checked on the server for every route.
- Optional **two-person approval** for devices tagged `production`: the approver must be a different user.
- First admin created by `scripts/create_user.py` (interactive, password via getpass).

### 8.3 Device credentials
- Device username/password/enable secret are entered **at push time**, held only in memory for
  that job (Pydantic `SecretStr`), and wiped when the job ends. Never written to MongoDB, logs,
  job records, exceptions or the browser's storage.
- Netmiko session logging disabled (or written to a masked log only).
- Secrets in generated commands, device output and config backups are **masked**
  (`password`, `secret`, `community`, `key-string`, `encrypted-password`, `pre-shared-key` lines).

### 8.4 Input validation
- All request models: `extra="forbid"`, max lengths, max list sizes, strict types.
- Validate with Python `ipaddress`: IPs inside their subnet, no host-address used as network,
  DHCP gateway inside its pool, no overlapping subnets, router-ID format, AS ranges.
- VLAN IDs 2–4094, reserved 1002–1005 rejected, no duplicates; VLAN names `[A-Za-z0-9_-]{1,32}`.
- Interface names validated against the model's port naming pattern.
- Hostnames, banners and descriptions: allowlist characters only (prevents command injection into
  the device CLI – no newlines, no `#`/`^C` banner delimiters, no `|`, no `;`).
- MongoDB queries built from validated fields only (no user JSON passed into queries).

### 8.5 Push safety
- Flow: validate → generate → **preview** → (approval if production) → connect → **backup running
  config** → **pre-checks** → apply → **error detection** → **verify** → save → done or rollback.
- **Denylist** checked on every final command list (including the custom-commands box):
  `reload`, `erase`, `write erase`, `delete`, `format`, `copy … startup-config` from untrusted sources,
  `no username`, `crypto key zeroize`, `request system zeroize`, `request system reboot`,
  `debug all`, `shutdown`/`no ip address` on the management interface.
  Matching is on **whole commands** (so `no shutdown` or `description reload-test` are allowed) and
  must also catch: Cisco abbreviations (`rel` = `reload`), a `do` prefix (`do reload`), any letter
  case, extra spaces, and several commands on one line.
- **Custom commands** are disabled for devices tagged `production`. On other devices they go through
  the same denylist and management-interface checks, and are written to the audit log.
- **Management-interface protection:** before applying, find the interface that holds the
  management IP (`show ip interface brief` etc.); block plans that shut it down, change its IP,
  move it to another VLAN, or remove SSH access on VTY lines while connected over SSH.
- **Rollback:** Cisco `archive` + `configure terminal revert timer N` then `configure confirm` after
  verification; Junos `commit confirmed N` then `commit`; others: restore from the backup.
  If the device becomes unreachable after applying, rollback and mark the job `rolled_back`.
- Stop on the first CLI error pattern (`% Invalid input`, `% Incomplete command`,
  `% Ambiguous command`, `syntax error`, `error:` …) and report the exact command.
- Telnet is allowed **only** for lab/emulator consoles on loopback or RFC1918 addresses, labelled
  insecure in the UI. Serial console is allowed for first-time setup. Everything else is SSH.
- SSH host keys: show the fingerprint on first connection, store it, and refuse to connect if it
  changes (MITM protection) unless an admin accepts the new key.

### 8.6 Audit and logging
- `audit_log` (append-only from the app): logins, user changes, device add/edit/delete, plan
  previews, pushes (with commands hash), approvals, rollbacks, settings changes. Fields: who,
  what, target, when, result.
- Logs never contain secrets. Errors returned to the browser never contain stack traces.

### 8.7 Supply chain
- Pin versions in `requirements.txt` and `package-lock.json`. Run `pip-audit`, `npm audit`, `bandit`
  and `ruff` before each release.

## 9. Testing rules
- Every phase ends with passing tests (`pytest` backend; `npm run build` must pass for frontend).
- Database tests use the real local MongoDB with a separate `netconfig_test` database that is dropped
  after the run. If MongoDB is not running they are skipped with a clear reason, but **a phase is
  not done while database tests are skipped**.
- Frontend tests: Vitest + @testing-library/react (devDependencies only, pinned versions).
- Driver tests: golden files for each feature and OS; unsupported features raise clear errors.
- Push engine tests use a **fake Netmiko connection** (no real device needed): success, CLI error
  mid-way, unreachable after apply → rollback, denylisted command blocked, management interface
  protected, secrets masked in job records.
- Security tests: wrong Host header rejected, cross-origin POST rejected, missing custom header
  rejected, unauthenticated/viewer access rejected, lockout works, oversize input rejected.
- Lab tests (manual, documented in `docs/LAB_TESTING.md`): each "tested" driver must be proven on
  an emulator before it is marked `tested`.

## 10. Working rules for Claude Code
- Work **one phase at a time** from `PROMPTS.md`. Start each phase with a plan, then implement.
- After each phase: run tests, run the app, update `README.md`/`docs/`, and give a short summary
  (what was built, how to run it, what is not done).
- Explain important code simply – the author is a 3rd-year cybersecurity student who will present
  this project in interviews.
- Never invent device commands you are unsure of: check vendor documentation, and mark anything
  untested as experimental.
- Do not add paid services, Docker, or new major libraries without asking. Never commit secrets.
  Never weaken a security rule to make a test pass.

