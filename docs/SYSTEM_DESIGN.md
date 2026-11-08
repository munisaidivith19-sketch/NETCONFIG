# NetConfig Studio – Backend System Design

Status: **Accepted (Phase 1A, 2026-11-08)**. Follows the architecture in `CLAUDE.md` section 2 and does
not change it. The open decisions from the draft were approved by the author on 2026-11-08.

---

## 1. Requirements

### 1.1 Functional
| # | Requirement | Phase |
|---|---|---|
| F1 | Local login with roles admin / engineer / viewer | 1 |
| F2 | Browse the catalog: category → brand → series → model → OS driver | 1 |
| F3 | Device inventory CRUD (never stores device passwords) | 1 |
| F4 | Build a ConfigPlan in a 5-step wizard; server validates and previews the commands | 2 |
| F5 | Push a plan safely: backup → pre-checks → apply → verify → save, or roll back | 3 |
| F6 | Two-person approval for devices tagged `production` | 3 |
| F7 | First-time setup over the serial console or lab console; router link wizard; multi-device push; templates | 3 |
| F8 | Multi-vendor drivers (Cisco IOS, Arista EOS, Junos, AOS-CX + experimental) | 4 |
| F9 | Live overview: reachability, topology (LLDP/CDP), KPIs | 4 |
| F10 | Optional AI drafting of plans (always validated, never pushed directly) | 5 |
| F11 | Append-only audit log of every security-relevant action | 1–5 |

### 1.2 Non-functional
| Concern | Target |
|---|---|
| Deployment | One engineer's Windows 11 laptop, native (no Docker), bound to `127.0.0.1` |
| Scale | 1–5 concurrent users (the author, plus a second user for approvals), ≤ 500 devices, ≤ 10 concurrent push jobs |
| Latency | API calls < 200 ms; previews < 500 ms; push jobs run for 10 s to a few minutes (device bound) |
| Availability | Best effort. The app may be stopped at any time, and no job may leave a device half-configured without a rollback path |
| Security | `CLAUDE.md` section 8 is mandatory. Device credentials live in memory only |
| Cost | Free tools only |

### 1.3 Constraints and assumptions
- Python 3.12, FastAPI, Pydantic v2, sync PyMongo, Netmiko (synchronous), React + Vite.
- MongoDB Community Server runs locally as a Windows service (`mongodb://127.0.0.1:27017/netconfig`).
- Single process, single machine. No message broker and no Redis, so job state is held in-process plus in MongoDB.
- The frontend is rebuilt in this project (see §9).

---

## 2. High-level design

```
Browser (React SPA, same origin)
   │  fetch() + cookie session + X-Requested-With: NetConfigStudio
   ▼
FastAPI app (uvicorn, 127.0.0.1:8000)
   ├─ Middleware chain (outer → inner)
   │    RequestID → SecurityHeaders → HostAllowlist → OriginAndCustomHeader → RateLimit(auth)
   ├─ Routers  /api/{health,auth,users,catalog,devices,plans,jobs,approvals,templates,hostkeys,audit}
   ├─ Dependencies  current_session → require_role(...)   (deny by default)
   ├─ Services
   │    validation  – cross-field checks (ipaddress)
   │    safety      – denylist, management-interface protection
   │    push        – one device: connect → backup → checks → apply → verify → save | rollback
   │    jobs        – ThreadPoolExecutor, state machine, progress, credential vault (memory only)
   │    audit       – append-only writer
   ├─ Drivers  registry: os_id → Driver (pure generators + parsers)
   │    cisco_ios · arista_eos · juniper_junos · aruba_aoscx · experimental/*
   ├─ Connection factory  → Netmiko ConnectHandler (ssh | serial | telnet-lab)   ← swapped for FakeConnection in tests
   └─ db.py  PyMongo client + index creation at startup
          ▼
     MongoDB (local)
```

**Main design rule:** drivers are *pure* (plan → commands, outputs → checks). All side effects
(network and database) live in `services/push.py` and `services/jobs.py`. This keeps the generators
testable with golden files and keeps the push engine testable with a fake connection.

---

## 3. Module responsibilities

| Module | Responsibility | Depends on |
|---|---|---|
| `main.py` | App factory, middleware order, router mounting, static `frontend/dist`, lifespan (DB indexes, job-pool shutdown) | everything |
| `config.py` | `Settings` (pydantic-settings): `ENV`, `HOST`, `PORT`, `ALLOW_REMOTE`, `MONGO_URI`, `SESSION_*`, `ENABLE_EXPERIMENTAL_DRIVERS`, `DEV_ORIGIN`, AI provider settings | – |
| `db.py` | Mongo client singleton, `get_db()`, `ensure_indexes()` | config |
| `security/guard.py` | Host allowlist, Origin and custom-header check, security headers/CSP | config |
| `security/sessions.py` | Create, validate and expire server-side sessions; cookie helpers | db |
| `security/passwords.py` | bcrypt (cost 12), password policy | – |
| `security/rbac.py` | `require_role("engineer")` dependency, role hierarchy | sessions |
| `security/ratelimit.py` | In-memory sliding window for `/api/auth/login` | – |
| `security/masking.py` | `mask_text()`, `mask_lines()` for secrets in commands, output and backups | – |
| `models/*` | Pydantic request/response models, all `extra="forbid"` | – |
| `api/*` | Thin routers: parse → authorise → call service → audit → respond | services |
| `drivers/base.py` | `Driver` Protocol, `Check`, `UnsupportedFeature` error | models |
| `drivers/registry.py` | `get_driver(os_id)`, honours `ENABLE_EXPERIMENTAL_DRIVERS` | drivers |
| `services/validation.py` | Section 8.4 checks; errors keyed by field path | models |
| `services/safety.py` | Denylist on final command list; management-interface rules | drivers |
| `services/push.py` | Executes one device step against a `Connection` | drivers, safety, masking |
| `services/jobs.py` | Job runner, state transitions, per-device lock, credential vault | push, db, audit |
| `services/audit.py` | `record(who, action, target, result, details)` | db |

---

## 4. Data model (MongoDB, database `netconfig`)

All documents carry `created_at` / `updated_at` (UTC). IDs are `ObjectId` unless stated otherwise.
**No collection ever contains a device password, enable secret or unmasked config.**

### 4.1 Collections

**`users`**
```json
{ "_id": ObjectId, "username": "alice", "password_hash": "$2b$12$…", "role": "admin|engineer|viewer",
  "disabled": false, "failed_logins": 0, "locked_until": null, "password_changed_at": ISODate }
```
Indexes: `username` unique (case-insensitive collation, strength 2).

**`sessions`**: stored server-side. The cookie holds only a random 256-bit token.
```json
{ "_id": "<sha256(token)>", "user_id": ObjectId, "role": "engineer", "created_at": ISODate,
  "last_seen": ISODate, "expires_at": ISODate /* created_at + 8 h */, "ip": "127.0.0.1", "ua": "…" }
```
Indexes: TTL on `expires_at` (`expireAfterSeconds: 0`); `user_id`.
The 30-minute idle timeout is checked in code (`now - last_seen > 30 min` → delete). The TTL index
only removes expired documents in the background, and the code check is what actually enforces the
timeout. Only the token **hash** is stored, so a database dump cannot be replayed as a cookie.

**`os_drivers`**: catalog data. `_id` is the `os_id` string.
```json
{ "_id": "cisco_ios", "name": "Cisco IOS / IOS-XE", "support": "tested|experimental|planned|inventory",
  "connections": ["ssh","serial","telnet_lab"], "apply_mode": "immediate|commit",
  "save_command": "write memory", "netmiko_device_type": "cisco_ios",
  "capabilities": ["vlans","access","trunk","svi","routed_if","dhcp","nat","static","ospf","eigrp","bgp","ssh"],
  "rollback": "revert_timer", "verified": false }
```

**`catalog_brands`**, **`catalog_series`**, **`catalog_models`**: kept separate so the wizard can
page through each level with indexed queries.
```json
// series
{ "_id": "cisco-catalyst-9200", "brand_id": "cisco", "name": "Catalyst 9200", "category": "switch", "os_id": "cisco_ios" }
// model
{ "_id": "cisco-c9200-24t", "series_id": "cisco-catalyst-9200", "brand_id": "cisco", "name": "C9200-24T",
  "category": "switch", "layer": 2, "ports": 24, "uplinks": 4, "poe": false,
  "port_prefix": "GigabitEthernet", "port_pattern": "^GigabitEthernet1/0/([1-9]|1[0-9]|2[0-4])$",
  "capabilities_override": [], "source": "sample", "verified": false }
```
Indexes: series `{brand_id, category}`; models `{series_id}`, `{category, brand_id}`, text index on `name`.

**`devices`**: inventory.
```json
{ "_id": ObjectId, "name": "core-sw1", "model_id": "cisco-c9200-24t", "os_id": "cisco_ios",
  "mgmt_ip": "10.0.0.2", "connection": { "method": "ssh|serial|telnet_lab", "port": 22, "serial_port": null },
  "location": "Lab rack 1", "tags": ["production"], "status": { "reachable": null, "checked_at": null },
  "created_by": ObjectId }
```
Indexes: `name` unique; `mgmt_ip` unique (partial: when present); `tags`; `os_id`.

**`host_keys`**: SSH fingerprint pinning (Phase 3).
```json
{ "_id": ObjectId, "device_id": ObjectId, "host": "10.0.0.2", "port": 22, "key_type": "ssh-rsa",
  "fingerprint_sha256": "SHA256:…", "first_seen": ISODate, "accepted_by": ObjectId,
  "pending": { "fingerprint_sha256": "…", "seen_at": ISODate } | null }
```
Indexes: `{host, port}` unique.

**`jobs`**: one document per push request. A job has 1..N **steps** (one per device), which covers
the router link wizard (2 steps) and multi-device pushes.
```json
{ "_id": ObjectId, "kind": "push|bootstrap|link|multi", "status": "<job status>",
  "requested_by": ObjectId, "approval": { "required": true, "expires_at": ISODate, "approved_by": ObjectId|null, "approved_at": null },
  "cancel_reason": "rejected|withdrawn" | null,
  "plan": { /* ConfigPlan with all SecretStr fields removed */ }, "plan_hash": "sha256:…",
  "steps": [
    { "device_id": ObjectId, "os_id": "cisco_ios", "status": "<step status>",
      "commands": ["…masked…"], "commands_hash": "sha256 of UNMASKED list (for audit/approval binding)",
      "timeline": [ { "state": "connecting", "at": ISODate } ],
      "backup": "…masked running-config…", "output": "…masked transcript…",
      "checks": [ { "name": "vlan 10 exists", "ok": true, "detail": "…" } ],
      "error": { "command": "switchport mode trunk", "message": "% Invalid input…" } | null }
  ],
  "created_at": ISODate, "finished_at": ISODate|null }
```
Indexes: `{created_at: -1}`; `{status, created_at: -1}`; `{status, "approval.expires_at"}` (expiry sweep); `{"steps.device_id": 1, created_at: -1}`; `requested_by`.

**Approval binding:** the approver approves a specific `plan_hash` and set of `commands_hash` values.
If the plan changes after approval, the hash changes and the approval no longer applies.

**`templates`** (Phase 3B): `{ _id, name, description, os_id|null, plan (no secrets), created_by }`. Index: `name` unique.

**`audit_log`**: append-only.
```json
{ "_id": ObjectId, "at": ISODate, "who": { "user_id": ObjectId, "username": "alice" } | null,
  "action": "auth.login|auth.logout|user.create|device.update|plan.preview|job.create|job.approve|job.rollback|…",
  "target": { "type": "device|user|job|session", "id": "…" }, "result": "ok|denied|failed",
  "details": { "commands_hash": "…" }, "request_id": "…", "prev_hash": "…", "hash": "…" }
```
Indexes: `{at: -1}`; `{action, at: -1}`; `{"who.user_id": 1, at: -1}`.
The app code only ever calls `insert_one` on this collection. A hash chain (`hash = sha256(prev_hash + canonical(doc))`)
makes tampering *detectable*. It cannot *prevent* tampering by someone with database access. That limit
is written down in `docs/SECURITY.md`.

**`settings`**: a single document, `_id: "global"` (approval required for production, revert timer
minutes, polling interval).

### 4.2 Why separate catalog collections instead of one nested document
A nested `brands → series → models` document would exceed practical sizes once the NetBox import runs
(thousands of models), and it cannot be indexed per level. The trade-off is three small lookups
instead of one, which is negligible locally.

---

## 5. Push-job lifecycle and state machine

### 5.1 Credentials and approval (important)
Credentials must never be stored, and an approval can take hours. So **credentials are not held in
memory while a job waits for approval**:

1. Engineer → `POST /api/jobs` (plan + device IDs, **no credentials**). The server validates, generates,
   runs the denylist and computes hashes.
   - Device tagged production → status `awaiting_approval`, with `approval.expires_at = created_at + 24 h`.
   - Otherwise → status `ready`.
2. Approver (a different user, admin) → `POST /api/jobs/{id}/approve` → `ready`, or
   `POST /api/jobs/{id}/reject` → `cancelled` (`cancel_reason: "rejected"`).
3. Not approved within 24 hours → `expired`. A sweep runs every minute in the job runner and also at
   startup. `approve` re-checks the deadline itself, so it never approves an expired job, even
   between sweeps.
4. The requester can withdraw → `POST /api/jobs/{id}/cancel` → `cancelled` (`cancel_reason: "withdrawn"`).
5. Engineer → `POST /api/jobs/{id}/run` with credentials (`SecretStr`) → `queued`. Credentials are accepted
   **only** in this call, and only from status `ready`. They go straight into the in-memory vault
   `{job_id: Credentials}` and are deleted in a `finally:` block when the job reaches a terminal state.

Status list (agreed, `CLAUDE.md` section 6): `awaiting_approval, ready, queued, connecting, backing_up,
checking, applying, verifying, saving, rolling_back, success, failed, rolled_back, blocked, cancelled, expired`.

### 5.2 Job state machine before execution
```
POST /jobs ─┬─ production ──► awaiting_approval ──approve──► ready ──run (+creds)──► queued ──► (step machine §5.3)
            │                     │  │                         │                     │
            │                     │  └─ 24 h, no approval ──► expired                │
            │                     └── reject / withdraw ──► cancelled ◄── withdraw ──┘ (cancel allowed until "applying")
            └─ not production ──────────────────────────────► ready
```

### 5.3 Step state machine (one device)
```
                 ┌───────────────────────── any error before apply ──────────────────────┐
                 │                                                                        ▼
queued → connecting → backing_up → checking ──(denylist / mgmt-if rule hit)──► blocked   failed
                                      │
                                      ▼
                                   applying ──(CLI error pattern)──► rolling_back ─► rolled_back
                                      │                                   ▲              │
                                      ▼                                   │   (rollback itself fails)
                                   verifying ──(check failed / device unreachable)──┘     ▼
                                      │                                               failed (+ "MANUAL ACTION REQUIRED")
                                      ▼
                                    saving ──► success
```
- **Terminal states:** `success`, `failed`, `blocked`, `rolled_back`, `cancelled`, `expired`.
- A cancel request during `queued`, `connecting`, `backing_up` or `checking` stops before any config
  command is sent → `cancelled`. From `applying` onward a cancel is refused, because stopping halfway
  is less safe than finishing or rolling back.
- **Rollback by driver strategy:**
  - `revert_timer` (Cisco): `archive` must exist. Apply inside `configure terminal revert timer N`. After verification
    passes, send `configure confirm`. If the app crashes or the connection drops, **the device reverts by itself**.
    This is the main safety reason for the design.
  - `commit_confirmed` (Junos): `configure private` → load → `commit check` → `commit confirmed N` → verify → `commit`.
  - `backup_restore` (others): replay the inverse or the saved backup. This is weaker and is flagged in the UI.
- **Pre-apply failures** (`connecting`, `backing_up`, `checking`) never touch the config, so they go to `failed` or `blocked` with no rollback.

### 5.4 Job status (aggregate of steps)
A single-device job shows its step's status. A multi-device job shows `awaiting_approval | ready |
queued | cancelled | expired` before running. While running it shows the status of the active step,
and at the end `success` (all steps), `rolled_back` (all applied steps reverted), `blocked`, or `failed`.
Each step's own status is always visible in `steps[]`.
Multi-device jobs stop launching new steps after the first failed step (default) so a bad plan does
not reach every switch. The router link wizard runs step B only if step A succeeds. If B fails, A is
rolled back as well (two-sided link consistency).

### 5.5 Concurrency
- `ThreadPoolExecutor(max_workers=4)`. A Netmiko session blocks, so threads fit.
- **Per-device lock** (`threading.Lock` per `device_id`): two jobs can never configure the same device at once.
- Progress is written to MongoDB on every transition. The browser polls `GET /api/jobs/{id}` every second
  (SSE is a possible later improvement).
- **Crash recovery:** at startup, any job left in a non-terminal running state is marked `failed` with
  "interrupted – verify device state". On Cisco and Junos the device has already reverted by itself (§5.3).

---

## 6. API surface

All routes are under `/api`. JSON only. Auth is the session cookie. State-changing methods need
`Origin` from the allowlist and `X-Requested-With: NetConfigStudio`. Roles: **V** viewer, **E** engineer, **A** admin
(higher roles include lower ones).

| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/health` | public | `{version, mongo: "ok"|"down"}` |
| POST | `/auth/login` | public | rate-limited; lockout 5 / 15 min; sets cookie |
| POST | `/auth/logout` | V | deletes the session |
| GET | `/auth/me` | V | current user and role |
| POST | `/auth/password` | V | change own password |
| GET/POST | `/users` | A | list / create |
| PATCH/DELETE | `/users/{id}` | A | role, disable, unlock; cannot delete or demote the last admin |
| GET | `/catalog/os-drivers` | V | |
| GET | `/catalog/brands?category=` | V | |
| GET | `/catalog/series?brand_id=&category=` | V | |
| GET | `/catalog/models?series_id=&q=&page=` | V | paged |
| GET | `/catalog/models/{id}` | V | |
| GET | `/devices?tag=&os_id=&q=&page=` | V | |
| POST | `/devices` | E | |
| GET/PATCH | `/devices/{id}` | V / E | |
| DELETE | `/devices/{id}` | A | |
| POST | `/plans/preview` | E | `{errors}` or `{commands(masked), warnings, unsupported}` |
| POST | `/jobs` | E | create (no credentials) → `awaiting_approval` or `ready` |
| POST | `/jobs/{id}/approve` | A | approver ≠ requester; binds to `plan_hash` |
| POST | `/jobs/{id}/reject` | A | |
| POST | `/jobs/{id}/run` | E | credentials in body → `queued` |
| POST | `/jobs/{id}/cancel` | E | only before `applying` |
| GET | `/jobs?status=&device_id=&page=` | V | history |
| GET | `/jobs/{id}` | V | progress + masked outputs |
| GET/POST | `/templates`, PATCH/DELETE `/templates/{id}` | V / E | |
| GET | `/hostkeys?pending=true` | A | |
| POST | `/hostkeys/{id}/accept` | A | accepts a changed key (audited) |
| GET | `/audit?action=&user=&from=&to=&page=` | A | |
| GET | `/status/overview` | V | Phase 4 KPIs |
| POST | `/ai/draft`, `/ai/explain` | E | Phase 5, optional |

**Errors:** `{ "error": { "code": "validation_error", "message": "…", "fields": {"vlans.0.id": "…"}, "request_id": "…" } }`.
There are never stack traces. Viewers get `403`, missing sessions get `401`, and wrong Host or Origin
gets `400` / `403` with no body detail.

---

## 7. Error handling and retries
- **Connect:** one retry after 3 s for timeouts only. Auth failures are never retried, so device
  AAA lockout is never triggered.
- **Apply:** no retries. The first CLI error pattern stops the step and triggers rollback.
- **Verify:** for convergence-sensitive checks (OSPF neighbour FULL, BGP Established), poll up to N times
  with a delay, inside the revert-timer window. The timer has to be longer than the verify window,
  and validation enforces that.
- **Database down:** `/health` reports it, writes fail with `503`. A running job keeps going, and the
  final state is retried 3 times.

---

## 8. Trade-offs

| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Job execution | In-process thread pool | Celery/RQ + Redis | One machine, free, no extra services on Windows. Cost: jobs die with the process (mitigated by revert timers + crash recovery) |
| Sync PyMongo | sync | Motor (async) | Netmiko is sync, so the push path runs in threads anyway. Simpler code |
| Progress transport | Polling 1 s | WebSocket / SSE | Simplest and works behind the strict CSP. Revisit if it feels slow |
| Sessions | Server-side Mongo | JWT | Instant revocation, idle timeout, nothing sensitive in the browser |
| Catalog | 3 collections | One nested doc | Indexed paging, NetBox import size |
| Approval vs credentials | Credentials supplied after approval | Hold creds during approval | Never keeps secrets in memory for hours |

## 9. Frontend
The original frontend was not available, so the author asked for it to be rebuilt (2026-11-08). It is a
Vite + React + React Router app in the liquid-glass design (`src/styles/tokens.css`, `app.css`), built
page by page alongside the backend phases. It always talks to the API through `src/lib/api.js`.

## 10. What to revisit as the system grows
- Multi-user or remote use (`ALLOW_REMOTE`) → TLS, a real reverse proxy, and possibly an external job queue.
- Thousands of devices → move polling into a separate worker process; consider SSE for progress.
- Audit integrity → ship the hash-chain head to an external location (signed export).
