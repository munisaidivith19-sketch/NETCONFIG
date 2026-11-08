# NetConfig Studio – Test Plan

Status: **Accepted (Phase 1A, 2026-11-08)**. Implements `CLAUDE.md` section 9. No phase is finished until its tests
pass (`pytest` in `backend/`, `npm run build` and `npm test` in `frontend/`).

## 1. Strategy

```
              Manual lab tests          ← each "tested" driver, on an emulator (docs/LAB_TESTING.md)
           E2E smoke (run skill)        ← app + fake device, once per phase
       API integration (TestClient)     ← HTTP layer, security middleware, RBAC, Mongo
  Unit + golden files + fake-Netmiko    ← most tests: fast, no network, no real device
```

Principles
- **No test needs a real device or the internet.** Netmiko is replaced by `FakeConnection`.
- **Security rules are tests, not comments.** Every section 8 rule has at least one test that fails if the rule is removed.
- **Never weaken a rule to make a test pass** (`CLAUDE.md` section 10).
- Tests are deterministic: frozen clock (`freezegun`-style fixture written by hand, so no new library), fixed IDs.

### Tooling
| Purpose | Tool |
|---|---|
| Backend runner | `pytest` (+ `pytest -q -x` locally) |
| HTTP tests | FastAPI `TestClient` (`httpx`) |
| Database | real local MongoDB, database `netconfig_test`, dropped after the session. Tests that only need logic use plain dicts |
| Static checks | `ruff`, `bandit -r app`, `pip-audit` |
| Frontend | `vite build`; Vitest + @testing-library/react (approved, devDependencies only, pinned versions) |

**Mongo in tests (agreed):** the real local MongoDB, using a separate database named `netconfig_test`
that is dropped at the start and end of the test session. The fixture refuses to run against any
other database name, so a test can never wipe `netconfig`. If MongoDB is not running, those tests are
skipped with the reason `"MongoDB not reachable at 127.0.0.1:27017 – start the MongoDB service"`.
**A phase is not done while any database test is skipped.** The phase review counts skips and
treats any skip as a failure.

### Layout
```
backend/tests/
├── conftest.py              # app fixture, test DB, users per role, logged-in clients, fake clock
├── unit/                    # validation, masking, safety, passwords, rbac, state machine
├── drivers/                 # golden-file harness + per-driver unsupported-feature tests
├── golden/<os_id>/<case>.json + <case>.txt     # plan input + expected commands
├── push/                    # FakeConnection scenarios
├── api/                     # endpoint + RBAC matrix
└── security/                # Host/Origin/header, lockout, sessions, oversize, secret leakage
```

## 2. Coverage targets
| Area | Target | Why |
|---|---|---|
| `services/validation.py`, `services/safety.py`, `security/*` | ≥ 95 % line, 100 % of rules | security boundary |
| `drivers/*` | every capability × every driver has a golden case | wrong commands = outage |
| `services/push.py`, `services/jobs.py` | every state transition in `SYSTEM_DESIGN.md` §5.2 and §5.3 | safety logic |
| `api/*` | every route × every role (RBAC matrix) | deny by default |
| Overall backend | ≥ 85 % line (`pytest --cov` only if `pytest-cov` is approved; otherwise reported manually) | |

## 3. Unit tests

### 3.1 Validation (`tests/unit/test_validation.py`), Phase 2B
Errors must be keyed by field path.
| Case | Input | Expected |
|---|---|---|
| VLAN range | `vlans[0].id = 1`, `4095` | `vlans.0.id` error |
| Reserved VLAN | `1002`…`1005` | rejected |
| Duplicate VLAN | two VLAN 10 | `vlans.1.id` "duplicate" |
| VLAN name | `"Sales Dept"` (space), 33 chars | rejected; `"Sales_Dept-1"` ok |
| IP outside subnet | SVI `10.0.10.300/24`, `10.0.11.1/24` on VLAN 10 network `10.0.10.0/24` | rejected |
| Network address used as host | `10.0.10.0/24` as interface IP | rejected |
| Overlapping subnets | `10.0.0.0/23` and `10.0.1.0/24` | rejected on the second |
| DHCP gateway outside pool | pool `10.0.20.0/24`, gw `10.0.21.1` | `dhcp.0.default_router` |
| Excluded range outside pool | | rejected |
| Router-ID | `1.2.3` / `256.0.0.1` | rejected |
| AS ranges | EIGRP 0, 65536; BGP 0, 4294967296 | rejected; BGP 4-byte `4200000000` ok |
| Interface name | `Gi1/0/99` on a 24-port model | rejected (model `port_pattern`) |
| **CLI injection** | hostname `sw1\nreload`, `sw1;reload`, `a|b`, banner containing `^C` or `#`, description with `\r` | all rejected |
| Unicode tricks | hostname with ` `, full-width `；` | rejected (allowlist, not denylist) |
| Size limits | 4 095 VLANs, 10 kB banner | 422 |
| `extra="forbid"` | unknown field `"run_as_root": true` | 422 |

### 3.2 Masking (`tests/unit/test_masking.py`), Phase 1B
Each line masks the value and keeps the keyword:
`username admin secret 9 $9$abc…`, `enable secret 5 …`, `snmp-server community public RO`,
`key-string 7 0822455D0A16`, `set system root-authentication encrypted-password "$6$…"`,
`pre-shared-key ascii-text "…"`, `password 7 …`. Case-insensitive. Multi-line input. Idempotent (masking twice gives the same result).
Negative case: `no password-encryption`-like lines keep their meaning.

### 3.3 Safety (`tests/unit/test_safety.py`), Phase 3A
| Case | Expected |
|---|---|
Matching rules (agreed): each line is normalised (trimmed, repeated spaces collapsed, lower-cased),
split into separate commands, and has a leading `do` removed. Then every word is matched as an IOS-style
abbreviation: a word matches a keyword if it is a prefix of it. Matching is on **whole commands**, so
a keyword inside an argument never matches.

| Case | Expected |
|---|---|
| Each denylist entry (`reload`, `erase startup-config`, `write erase`, `delete flash:x`, `format flash:`, `copy tftp: startup-config`, `no username admin`, `crypto key zeroize`, `request system zeroize`, `request system reboot`, `debug all`) | blocked, offending command reported |
| Abbreviations: `rel`, `relo`, `wr er`, `era start`, `del flash:x`, `cry key zero rsa`, `req sys reboot`, `deb all` | blocked |
| `do` prefix: `do reload`, `DO  wr  erase`, `do rel` | blocked |
| Letter case and spacing: `  RELOAD`, `Reload`, `write    erase`, tab characters | blocked |
| Several commands on one line: `vlan 10 ; reload`, `hostname a \| reload`, `name x\nreload`, `exit && reload` | blocked (and validation rejects `;` / `\|` / newlines first; the denylist still checks independently in case validation is bypassed) |
| Whole-command matching: `no shutdown` (non-mgmt port), `description reload-test`, `vlan 10 name delete_me`, `ip domain name format.lab` | **allowed** |
| Ambiguous short words that are not denylisted on their own: `de` (debug / delete / description), `re` | treated as **blocked** when any denylisted keyword fits and the command cannot be proved safe (fail closed) |
| Mgmt interface `Vlan1` holds `10.0.0.2`: plan shuts `Vlan1` / changes its IP / moves the uplink to another VLAN / sets `transport input none` on VTY | blocked |
| Same plan on a non-management interface | allowed |

Custom-commands box (agreed):
| Case | Expected |
|---|---|
| Device tagged `production` + any custom command | rejected at preview and at job creation (`custom_commands not allowed on production devices`) |
| Lab device + safe custom command | allowed, goes through the denylist and management-interface checks |
| Lab device + `do rel` in custom commands | blocked |
| Any accepted custom commands | audit entry `plan.custom_commands` with who, device, the commands (masked) and their hash |

### 3.4 Security primitives
- `passwords`: bcrypt cost 12 (check the hash prefix `$2b$12$`); a 11-character password is rejected; a 12-character password is accepted; comparison never raises on malformed hashes.
- `rbac`: role ordering viewer < engineer < admin.
- `sessions`: token stored only as sha256; idle expiry at 30 min (+1 s); absolute expiry at 8 h even while active.

### 3.5 Job state machine (`tests/unit/test_job_states.py`), Phase 3A
Table-driven: every allowed transition succeeds; every other transition raises. Terminal states
(`success, failed, blocked, rolled_back, cancelled, expired`) cannot change. Credentials vault is empty
after every terminal state.
| Case | Expected |
|---|---|
| Production job not approved after 24 h (fake clock 24 h + 1 s) | `expired`; approve then returns 409 |
| Approve at 23 h 59 m | `ready` |
| Approve exactly at the deadline but before the sweep runs | refused (approve checks the deadline itself) |
| Reject | `cancelled`, `cancel_reason = "rejected"`, audited |
| Requester withdraws from `awaiting_approval` / `ready` / `queued` / `checking` | `cancelled`, `cancel_reason = "withdrawn"`, no config commands sent |
| Withdraw during `applying` | 409, the job continues to success or rollback |
| `run` with credentials while `awaiting_approval`, `expired` or `cancelled` | 409, and the credentials are never placed in the vault |
| Credentials field present on `POST /jobs` | 422 (`extra="forbid"`) |

## 4. Golden-file driver tests (Phase 2B, 4A)

Harness: for each `tests/golden/<os_id>/*.json` (a ConfigPlan), call `driver.generate(plan)` and compare
with `<case>.txt` exactly. `UPDATE_GOLDEN=1 pytest tests/drivers` rewrites the files, and changed golden
files must be reviewed in the diff by a human. That is the point of the test.

Cases per driver (one file each):
`basic_hostname_domain`, `ssh_v2`, `hardening`, `vlans_multi`, `access_ports_range`, `portfast_portsecurity`,
`trunk_allowed_native`, `svi_ip_routing`, `routed_interface`, `dhcp_pool_excluded`, `nat_overload_acl`,
`static_routes`, `ospf_area0`, `eigrp_named_or_classic`, `bgp_ebgp_neighbor`, `full_campus` (everything combined).

Each driver also has:
- `verify_commands` golden list per case.
- `check()` tests with **recorded sample outputs** (`tests/golden/<os_id>/outputs/show_vlan_brief.txt` …) taken from the vendor docs in `docs/drivers/<os>.md` (and replaced with real lab output later): pass and fail versions.
- `error_patterns()`: each pattern matches its documented sample error.
- Unsupported features: e.g. EIGRP on Junos → `UnsupportedFeature("eigrp not supported on Juniper Junos")`, never an empty list.
- Secrets in the preview are masked; secrets in the real push list are not (the device needs them), and that list is never stored.

## 5. Push-engine tests with a fake Netmiko connection (Phase 3A, 3B)

`FakeConnection` implements the `Connection` protocol and is scripted:
```python
fake = FakeConnection(
    responses={"show running-config": RUNNING, "show ip interface brief": IP_BRIEF},
    fail_on={"switchport trunk native vlan 99": "% Invalid input detected at '^' marker."},
    unreachable_after_apply=False,
)
```
It records every sent command so tests can assert the exact order.

| # | Scenario | Assert |
|---|---|---|
| P1 | Success, Cisco | order = backup → `archive` check → `configure terminal revert timer N` → commands → verify → `configure confirm` → save; status `success` |
| P2 | CLI error mid-way | stops at the failing command, reports it, rollback runs, status `rolled_back`, later commands never sent |
| P3 | Unreachable after apply | rollback (or reliance on the revert timer) → `rolled_back`; job notes the timer |
| P4 | Verification fails (VLAN missing) | rollback → `rolled_back` |
| P5 | Denylisted command | status `blocked`; **zero** config commands sent |
| P6 | Management interface protected | `blocked` before `applying` |
| P7 | Junos | `configure private` → `commit check` → `commit confirmed N` → verify → `commit` |
| P8 | Backup-restore driver | on error, backup replayed |
| P9 | Rollback itself fails | `failed` + "MANUAL ACTION REQUIRED" |
| P10 | Auth failure | `failed`, sanitised message, no retry |
| P11 | RSA `replace? [yes/no]` prompt | answered as designed; never hangs |
| P12 | **Secrets never stored** | after P1–P11, search every document in `jobs` and `audit_log`, plus captured logs, for the test password, enable secret and SNMP community: no match |
| P13 | Vault cleanup | vault empty after success, error and exception paths |
| P14 | Host key | first connect stores the fingerprint; a changed key → refused; admin accept → allowed (audited) |
| P15 | Telnet restrictions | telnet to `8.8.8.8` rejected; to `127.0.0.1` / `192.168.x` allowed and labelled insecure |
| P16 | Per-device lock | two jobs on one device → second waits or is refused |
| P17 | Multi-device | step 2 not started after step 1 fails |
| P18 | Link wizard | side B fails → side A rolled back |
| P19 | Crash recovery | job left `applying` at startup → `failed` "interrupted" |
| P20 | Bootstrap (serial) | initial-config dialog answered "no"; SSH configured; connection method switched to SSH only after a test login works |

## 6. Security tests (`tests/security/`)

Phase 1B unless noted. Each is an HTTP test against the real middleware stack.
| # | Test | Expected |
|---|---|---|
| S1 | `Host: evil.com` (DNS rebinding) on GET and POST | 400 |
| S2 | `Host: 127.0.0.1:8000` and `localhost:8000` | allowed |
| S3 | POST with `Origin: https://evil.com` | 403 |
| S4 | POST without `X-Requested-With` | 403 |
| S5 | POST with `Content-Type: text/plain` (simple-request CSRF) | rejected |
| S6 | No CORS headers in production; dev allows only the Vite origin | |
| S7 | Response headers: CSP `default-src 'self'` without `unsafe-inline` for scripts, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `frame-ancestors 'none'`, `Referrer-Policy: no-referrer` | present on every response, including errors |
| S8 | `ENV=production`: `/docs`, `/redoc`, `/openapi.json` | 404 |
| S9 | Unauthenticated request to every non-public route | 401 |
| S10 | **RBAC matrix**: every route × {viewer, engineer, admin} against the table in `SYSTEM_DESIGN.md` §6 | 403 where not allowed. The test is generated from the app's route list, so a new route without an RBAC entry fails the test |
| S11 | Lockout: 5 bad passwords → locked; the correct password during lockout fails; it works after 15 min (fake clock) | |
| S12 | Login rate limit per IP | 429 |
| S13 | Same error and similar timing for an unknown user and a wrong password (no user enumeration) | |
| S14 | Session cookie flags: `HttpOnly`, `SameSite=Strict`, `Path=/`; logout invalidates on the server | |
| S15 | Idle and absolute expiry | 401 |
| S16 | Oversize body (> 1 MB), list over its limit, string over max length | 413 / 422 |
| S17 | Errors contain no stack trace and include a `request_id` | |
| S18 | Mongo injection: `{"name": {"$ne": null}}` in query or body | 422 |
| S19 | Two-person approval: requester cannot approve their own job; approval breaks if the plan changes (Phase 3A) | |
| S20 | Last admin cannot be deleted or demoted | |
| S21 | Audit entries are written for login, failed login, user and device changes, preview and push; audit API is admin-only | |
| S22 | AI provider receives no credentials, secrets or unmasked config; prompt-injection text in device output does not change the plan (Phase 5A) | |
| S23 | Startup refuses `HOST=0.0.0.0` unless `ALLOW_REMOTE=true` | |

Static and supply-chain checks (before every phase review): `ruff check`, `bandit -r backend/app`
(no high findings), `pip-audit` and `npm audit` (no known high or critical findings, or a documented accepted risk).

## 7. API integration tests (`tests/api/`)
Per router: happy path, validation errors, 404s, pagination limits, and audit side effects.
Catalog: brand → series → model filters return the seeded sample. Devices: unique name and IP;
`production` tag; any `password` field is rejected by `extra="forbid"`.

## 8. Manual lab tests (`docs/LAB_TESTING.md`, Phase 3B and 4A)

A driver moves from `experimental` to `tested` **only** after its lab checklist passes on an emulator,
and the author confirms it.
| Driver | Emulator |
|---|---|
| cisco_ios | Cisco IOSv / IOSvL2 in GNS3 or CML-Free |
| arista_eos | cEOS-lab |
| juniper_junos | vJunos-switch / vJunos-router |
| aruba_aoscx | AOS-CX Simulator |
| mikrotik (experimental) | CHR |

Checklist per driver: bootstrap over the console → SSH login works; each golden case pushed and
verified with the driver's show commands; forced CLI error → rollback confirmed on the device; pull
the link after apply → device reverts (revert timer / commit confirmed); change the SSH host key →
the app refuses; production approval flow with two users. Record the date, emulator image version
and result in the table.

## 9. Frontend tests
- `npm run build` must pass (required by `CLAUDE.md`).
- Vitest + @testing-library/react (approved, devDependencies only, pinned exact versions): login flow, 401 redirect,
  API client always sends `X-Requested-With`, no tokens or credentials in `localStorage`/`sessionStorage`,
  credentials field cleared after a push, wizard step focus management.
- Phase 4C: manual accessibility and responsive checks (375 px, both themes) with the run skill.

## 10. When tests run
| When | What |
|---|---|
| Every change | `pytest -q` for the touched area |
| End of every part | full `pytest`, `ruff`, `npm run build` |
| Phase review | everything above + `bandit`, `pip-audit`, `npm audit`, E2E smoke with the fake device |
| Before marking a driver `tested` | lab checklist (§8) |

## 11. Known gaps and risks
- Golden files written from documentation can be wrong in the same way as the driver. Only lab tests catch this, so drivers stay `experimental` until §8 passes.
- `FakeConnection` cannot reproduce every prompt or timing quirk; P11 and P20 need lab confirmation.
- Memory wiping cannot be proven in Python (see ADR-0004). P13 tests only that references are dropped.
