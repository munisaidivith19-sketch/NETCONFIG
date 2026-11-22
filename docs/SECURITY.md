# NetConfig Studio – Security

The threat model, the controls, and an honest list of limitations. Rules come from CLAUDE.md §8. Reviewed in
Phase 5B on 2026-11-21. The demo steps are in `docs/SECURITY_TESTING.md`.

## 1. What we protect

| Asset | Why it matters |
|---|---|
| Network devices (running configuration, reachability) | A bad push can cause an outage or lock the engineer out. |
| Device credentials (username, password, enable secret) | They give full control of the network. |
| NetConfig Studio accounts and sessions | A session can push configuration. |
| Configuration backups and job records | They show the network layout, and could hold secrets if they were not masked. |
| Audit log | It is the evidence of who changed what. |
| AI provider API key | It costs quota, and it is tied to the engineer's account. |

## 2. Trust boundaries

```
 [ Other websites in the same browser ] ─ ✗ Host / Origin / custom header / no CORS
                    │
 [ Engineer's browser ] ──HTTP on 127.0.0.1 (HTTPS when remote)──► [ FastAPI app ]
                                                                     │   │    │
                        SSH (pinned host key) / lab Telnet / serial ─┘   │    └─ HTTPS ► [ AI provider ]
                                                         [ Devices ]     │            (optional, masked text)
                                                                [ MongoDB 127.0.0.1 ]
```

1. **Browser ↔ local API.** Any website the engineer opens can send requests to `127.0.0.1`.
2. **API ↔ devices.** The network path can be tampered with (man in the middle), and device output is
   untrusted.
3. **API ↔ MongoDB.** The database is local. Anything stored there can be read by whoever can read the
   database.
4. **API ↔ AI provider (optional).** Hosted providers are third parties outside the network. Ollama stays on
   the PC.

## 3. Why a local app needs Host and Origin checks

"It only listens on 127.0.0.1" is not enough, because the attacker's code runs in the engineer's own browser:

- **CSRF to localhost.** A page on `evil.example` can `fetch("http://127.0.0.1:8000/api/jobs", {method:
  "POST"})`. The browser sends the request, including our session cookie if SameSite allows it. Defences:
  - the session cookie is `SameSite=Strict`;
  - every state-changing request needs an allowed `Origin`;
  - every state-changing request needs the custom header `X-Requested-With: NetConfigStudio`.

  A cross-site page can only add a custom header after a CORS preflight. We never answer preflights
  (`OPTIONS` → 403) and have no CORS middleware, so the browser never sends the header.
- **DNS rebinding.** The attacker's domain first resolves to their server, then is re-pointed to
  `127.0.0.1`. The browser now treats our API as *same origin* with `evil.example`, so Origin and CORS
  checks do not help. The request still carries `Host: evil.example`, so the **Host allowlist**
  (`127.0.0.1:<port>`, `localhost:<port>`, `[::1]:<port>`) rejects it with 400.

## 4. STRIDE threat model

S = spoofing, T = tampering, R = repudiation, I = information disclosure, D = denial of service,
E = elevation of privilege.

### 4.1 Browser and frontend

| | Threat | Control | Where |
|---|---|---|---|
| S | Another site acts as the logged-in engineer (CSRF) | SameSite=Strict cookie, Origin allowlist, custom header, no CORS | `security/guard.py`, `api/auth.py` |
| T | Injected script changes a plan before preview | CSP `script-src 'self'` with no inline script; React escapes all text, including AI answers | `security/guard.py: CSP` |
| I | Session token stolen by script | httpOnly cookie; the token is never in JS, localStorage or URLs | `api/auth.py`, `frontend/src/lib/api.js` |
| I | Device passwords kept by the browser | Typed per run and cleared after submit. Device secret fields opt out of autofill and of password-manager saving (`NO_SAVE`) | `RunForm.jsx`, `ui.jsx: NO_SAVE` |
| I | Page framed for clickjacking | `X-Frame-Options: DENY` and `frame-ancestors 'none'` | `security/guard.py` |
| E | Viewer reaches engineer actions by editing the UI | Every role is checked on the server; the UI only hides buttons | `security/rbac.py` |

### 4.2 Local API (FastAPI)

| | Threat | Control | Where |
|---|---|---|---|
| S | DNS rebinding | Host header allowlist | `security/guard.py`, `config.py: allowed_hosts` |
| S | Password guessing | bcrypt cost 12, 12-character minimum, lockout for 15 min after 5 failures (atomic counter), 10 login attempts per minute per IP, same message and timing for unknown users | `services/users.py`, `security/passwords.py`, `api/auth.py` |
| S | Session theft or reuse | 256-bit random token, stored only as a SHA-256 hash; 8 h absolute and 30 min idle limits; logout and password change revoke sessions | `security/sessions.py` |
| T | Command injection into the device CLI through form fields | Character allowlists for hostnames, descriptions and banners (no newline, `#`, `^C`, `\|`, `;`); `extra="forbid"`; strict types; length and list limits | `models/plan.py`, `models/common.py` |
| T | NoSQL injection | Queries are built only from validated scalars; regex input is escaped and pattern-checked | `api/devices.py`, `api/catalog.py`, `api/audit.py` |
| R | "I didn't push that" | Append-only audit log with a hash chain. It records logins, user and device changes, previews, pushes (with the commands hash), approvals, rollbacks and AI use | `services/audit.py` |
| I | Stack traces or secrets in errors | Generic 500 with a request ID; only the exception *type* is logged | `errors.py` |
| I | API docs reveal the attack surface | `/docs` and `/openapi.json` are off when `ENV=production` | `main.py` |
| D | Oversized or flooding requests | 1 MB body limit, JSON only, no chunked bodies; rate limits on login, discovery, refresh and AI | `security/guard.py`, `security/ratelimit.py` |
| E | Engineer approves their own production change | The approver must be a different admin; the server checks the requester's ID | `services/jobs.py: approve` |
| E | A new endpoint forgets authentication | `assert_all_routes_protected` stops the app from starting; the RBAC table test fails | `security/rbac.py`, `tests/security/test_auth.py` |
| S/I | App exposed to the LAN | Binds to 127.0.0.1. Another address needs `ALLOW_REMOTE=true` **and** `SSL_CERTFILE`/`SSL_KEYFILE` (HTTPS, Secure cookies, HSTS) and logs a startup warning | `config.py: check_bind_address`, `__main__.py` |

### 4.3 Device connections

| | Threat | Control | Where |
|---|---|---|---|
| S | Man in the middle impersonates a switch | SSH host key pinned on first use; a changed key is refused before the password is sent; only an admin can accept a new key (audited) | `services/hostkeys.py`, `services/connection.py` |
| I | Credentials sniffed | SSH only. Telnet is allowed only for lab consoles on loopback or RFC1918 addresses, checked when the device is saved **and** again when Telnet is opened, and labelled insecure in the UI | `models/device.py`, `services/connection.py` |
| I | Credentials stored or logged | `SecretStr`, held in an in-memory vault for one job and removed in `finally`. Never in MongoDB, logs or job records. Netmiko session log is off. Transcripts are scrubbed of the actual secret values and masked | `services/jobs.py: Vault`, `services/push.py: Transcript` |
| T | Destructive command (`reload`, `write erase`, …) | Whole-command denylist on the final list, including custom commands. It catches abbreviations, a `do` prefix, case, spacing and several commands on one line. Device shells (`bash`, `tclsh` …) are blocked too | `services/safety.py` |
| T/D | Change locks the engineer out | Before applying, the interface holding the management IP is found. Plans that shut it down, change its IP, remove its VLAN, or remove SSH/VTY access while connected over SSH are blocked | `services/safety.py: check_management`, `services/push.py` |
| D | Change breaks the device | Backup first; stop at the first CLI error; verify with `show` commands; roll back (Cisco revert timer, Junos `commit confirmed`, or restore from backup); the device rolls itself back if it becomes unreachable | `services/push.py`, `drivers/*` |
| T | Device output injects into later commands or the AI | Output is parsed, never executed. For the AI it is masked and passed as delimited untrusted data | `services/ai.py` |
| E | Custom commands on production | Disabled for devices tagged `production`; audited elsewhere | `services/planning.py` |

### 4.4 Database (local MongoDB)

| | Threat | Control | Where |
|---|---|---|---|
| I | Database copy reveals secrets | No device passwords stored; session tokens stored only as hashes; user passwords as bcrypt; plans, outputs and backups masked | `security/masking.py`, `models/job.py` |
| T | Audit entries edited or deleted | Hash chain plus `GET /api/audit/verify`. This is *detection*, not prevention (see limitations) | `services/audit.py` |
| S | Another program on the PC talks to MongoDB | MongoDB listens on 127.0.0.1 only (default install) | MongoDB config |

### 4.5 AI provider (optional, off by default)

| | Threat | Control | Where |
|---|---|---|---|
| I | Secrets or credentials sent to a third party | All text masked before sending; credentials never reach these endpoints. Ollama keeps everything on the PC | `services/ai.py: clean` |
| T | Prompt injection from device output | Data only in `<untrusted_data>` tags in the user message; copies of those tags removed; the system prompt says the block is data; the answer is plain text that nothing acts on | `services/ai.py` |
| T | AI draft pushes something harmful | A draft only fills the form. It is validated, previewed, safety-checked and approved like any plan; `ssh` and custom commands are removed | `services/ai.py: parse_draft`, `AiDraft.jsx` |
| I | API key leaked | `SecretStr`, sent only in a header, https only (plain http only to the fixed loopback Ollama URL) | `services/ai.py` |
| D | Quota exhaustion | Engineers only, 10 requests per minute, 30 s timeout, 200 kB reply cap | `api/ai.py` |

## 5. CLAUDE.md §8 compliance (Phase 5B review)

Status before the review → after. Each `PARTIAL` was fixed in this phase with a test.

| Rule | Status | Evidence (file:line) |
|---|---|---|
| 8.1 Bind 127.0.0.1 by default | PASS | `app/config.py:17` |
| 8.1 Remote bind needs ALLOW_REMOTE, **HTTPS** and login, and warns | PARTIAL → PASS (HTTPS was not enforced). 5C review: a wildcard `HOST=0.0.0.0` is refused (no browser sends it as Host, so the allowlist could not name the real address); half an HTTPS setup is refused; origins follow what is really served; HSTS only in remote mode (on `localhost` it would pin every port for a year) | `app/config.py` `check_bind_address`, `hsts`; `app/security/guard.py` (HSTS); tests `test_refuses_non_local_bind_without_allow_remote_and_https`, `test_https_files_checked_on_every_bind`, `test_origin_scheme_follows_what_is_served`, `test_https_on_localhost_secure_cookie_without_hsts` |
| 8.1 Host header allowlist | PASS | `app/config.py:67`, `app/security/guard.py:93` |
| 8.1 Origin check and custom header on state-changing requests | PASS | `app/security/guard.py:104`, `:109` |
| 8.1 No CORS; preflights refused | PASS | `app/security/guard.py:97` |
| 8.1 CSP, nosniff, frame-ancestors, Referrer-Policy | PASS | `app/security/guard.py:26` |
| 8.1 `/docs` off in production | PASS | `app/main.py:61` |
| 8.2 bcrypt ≥ 12, 12-character minimum | PASS | `app/config.py:36`, `app/security/passwords.py:5` |
| 8.2 Lockout after 5 failures for 15 min | PARTIAL → PASS (read-modify-write counter could undercount parallel guesses; 5C review: a correct guess that was in bcrypt while parallel guesses locked the account cleared the new lock, so success now only clears an account that is still unlocked) | `app/services/users.py` `authenticate`; tests `test_lockout_counts_parallel_failures`, `test_correct_password_does_not_clear_a_lock_set_meanwhile` |
| 8.2 httpOnly SameSite=Strict cookie; server-side session with TTL, 8 h / 30 min | PASS | `app/api/auth.py:27`, `app/security/sessions.py:48`, `app/db.py:37` |
| 8.2 Roles checked on the server for every route | PASS | `app/security/rbac.py:32`, `:85` |
| 8.2 Two-person approval with a different approver | PASS | `app/services/jobs.py:262` |
| 8.2 First admin via interactive script with getpass | PASS | `scripts/create_user.py:32` |
| 8.3 Credentials only at push time, in memory, wiped at job end | PASS (see limitation 7.1) | `app/models/job.py:19`, `app/services/jobs.py:76` |
| 8.3 Never in MongoDB, logs, job records, exceptions | PASS | `app/services/push.py:64`, `app/errors.py:76` |
| 8.3 Never in the browser's storage | PARTIAL → PASS (device secret fields carry the password-manager opt-outs `NO_SAVE`; every password field is a `SecretInput` with `autocomplete="new-password"`, because Chromium ignores `off` there and would autofill the engineer's saved NetConfig password into a device's new local admin password) | `frontend/src/components/ui.jsx` `NO_SAVE`/`SecretInput` (test `SecretInput.test.jsx`), `RunForm.jsx`, `Devices.jsx`, `Overview.jsx` |
| 8.3 Netmiko session log off | PASS | `app/services/connection.py:182` |
| 8.3 Masking of secret lines | PASS | `app/security/masking.py:8` |
| 8.4 `extra="forbid"`, max lengths and list sizes | PASS | `app/models/common.py:13`, `app/models/plan.py` |
| 8.4 **Strict types** | PARTIAL → PASS (lax mode accepted `"10"` for an int and `"yes"` for a bool) | `app/models/common.py:13` |
| 8.4 IP, subnet, VLAN rules (2–4094, 1002–1005 reserved) | PASS | `app/services/validation.py:16` |
| 8.4 Interface names checked against the model's pattern | PASS | `app/services/validation.py:131` |
| 8.4 Text allowlists (hostname, banner, description) | PASS | `app/models/plan.py:15` |
| 8.4 Queries from validated fields only | PASS | `app/api/devices.py:130` (escaped and pattern-checked) |
| 8.5 Push flow: backup → pre-checks → apply → verify → save/rollback | PASS | `app/services/push.py:179`, `:189`, `:411` |
| 8.5 Denylist on whole commands (abbreviations, `do`, case, spaces, several per line) | PARTIAL → PASS (features that store a command and run it later got past it: IOS `event manager`/`kron`/`alias`/`macro`, EOS `event-handler`/`schedule`/`alias`/`daemon`, Junos `set event-options`/`set system scripts`, AOS-CX `job`/`schedule`/`alias`). A keyword list cannot be complete: see limitation 10 | `app/services/safety.py:17`, each driver's `denylist()`; tests `test_cisco_deferred_execution_blocked`, `test_driver_denylist` |
| 8.5 Custom commands off for production, checked and audited elsewhere | PASS | `app/services/planning.py:105` |
| 8.5 Management-interface protection | PASS | `app/services/safety.py:131` |
| 8.5 Stop at the first CLI error and report the command | PASS | `app/services/push.py:93`, `app/drivers/base.py:127` |
| 8.5 Rollback per OS; unreachable after apply → rollback | PASS | `app/drivers/base.py:130` |
| 8.5 Telnet only to lab loopback/RFC1918 | PASS, hardened (now also checked when the connection opens) | `app/models/device.py:24`, `app/services/connection.py:196` |
| 8.5 SSH host keys pinned; change refused until an admin accepts | PASS | `app/services/hostkeys.py:20`, `app/services/connection.py:169` |
| 8.6 Append-only audit log of the listed events | PASS (no settings API exists yet, so there are no settings events) | `app/services/audit.py:44`, `:75` |
| 8.6 No secrets in logs, no stack traces to the browser | PASS | `app/errors.py:76` |
| 8.7 Pinned versions; pip-audit, npm audit, bandit, ruff | PARTIAL → PASS (setuptools in `.venv` had 9 CVEs; now pinned to 84.2.1) | `backend/requirements.txt:20`, `docs/ACCEPTED_RISKS.md` |

## 6. Tool results (2026-11-21)

| Tool | Result |
|---|---|
| `bandit -c pyproject.toml -r app scripts` | 0 issues |
| `ruff check .` | clean |
| `npm audit` | 0 vulnerabilities |
| `pip-audit` | `dnspython` (2 CVEs) and `filelock` (17 CVEs). Both are accepted with reasons in `docs/ACCEPTED_RISKS.md`, and both fixes need Python ≥ 3.11. `setuptools` fixed. |

## 7. Limitations (honest)

1. **Memory wiping.** Python cannot overwrite strings. "Wiped" means every reference is dropped and the vault
   entry is deleted. A memory dump of the running process during a job could still reveal a device
   password (ADR-0004).
2. **Audit chain.** The hash chain detects editing or deletion *by the app's rules*. Someone with write access
   to MongoDB can rewrite the whole chain. For stronger evidence, export the log regularly to a write-once
   location.
3. **MongoDB has no login by default.** It listens only on 127.0.0.1, but any program running as any user on
   the PC can read it (masked backups, job history, user hashes). On a shared PC, enable MongoDB access
   control and put the credentials in `MONGO_URI` in `backend\.env`.
4. **The PC itself is trusted.** Malware on the engineer's PC can read keystrokes and process memory. That is
   outside what an app can defend against.
5. **Browser password managers.** The device fields opt out of saving, but a password manager can still
   ignore the hints and offer to save. Decline it.
6. **Hosted AI providers see masked configuration.** Secrets are masked, but the network layout (VLANs,
   addresses, interface names) is sent to Groq or Gemini. Use `AI_PROVIDER=ollama` or `off` where that is not
   acceptable.
7. **Drivers are experimental** until the lab checklist (`docs/LAB_TESTING.md`) passes on an emulator. The
   safety layer does not depend on the driver, but verification and rollback commands do.
8. **The simulator is not a device.** It accepts every command, so rollback and host-key changes must be shown
   with the automated tests or in the lab.
9. **Self-signed certificates for remote mode** are the engineer's responsibility. The app refuses to start
   remote mode without a certificate and key, but it does not check who issued the certificate.
10. **The custom-commands box is checked against a denylist, not an allowlist.** Each vendor has features that
    store CLI text and run it later (schedulers, event handlers, macros, aliases). The known ones are denied, but
    a new firmware feature would get past the list until it is added. Custom commands are off for production
    devices and audited elsewhere. An allowlist of top-level commands per driver is the stronger fix
    (`docs/TECH_DEBT.md`).
