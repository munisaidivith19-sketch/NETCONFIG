# Demonstrating the security controls

A script for showing each control live, for example in an interview. Each section has:
- **Show:** what to do on screen;
- **Proof:** the automated test that checks the same thing on every run;
- **Say:** one or two sentences explaining why it matters.

The threat model is in `docs/SECURITY.md`.

## 0. Setup (once, about 5 minutes)

```powershell
# Terminal 1 – the app in simulation mode (pushes go to a pretend Cisco switch, never the network)
cd backend
$env:SIMULATE_DEVICES="true"; .venv\Scripts\python -m app

# Terminal 2 – three users (passwords typed with getpass, never shown)
cd backend
.venv\Scripts\python scripts\create_user.py     # demo-admin, role admin
.venv\Scripts\python scripts\create_user.py     # demo-eng,   role engineer
.venv\Scripts\python scripts\create_user.py     # demo-view,  role viewer
```

Open `http://127.0.0.1:8000`, sign in as **demo-eng**, and add a device: model *IOSvL2 (lab)*, management IP
`10.0.0.2`. The simulator puts that address on `Vlan1`.

`curl.exe` ships with Windows 11. Use `curl.exe`, not `curl`, which in Windows PowerShell 5.1 is an alias for
`Invoke-WebRequest`.

## 1. Host header allowlist (DNS rebinding)

**Show**
```powershell
curl.exe -i http://127.0.0.1:8000/api/health                              # 200
curl.exe -i http://127.0.0.1:8000/api/health -H "Host: evil.example:8000"  # 400 "Host not allowed."
```
**Proof:** `pytest tests/security/test_guard.py -k "host" -v`

**Say:** "With DNS rebinding the attacker's domain points at 127.0.0.1, so the browser thinks my API is the
attacker's site. The Host header still says `evil.example`, so the app refuses anything that is not
`127.0.0.1` or `localhost` on its own port."

## 2. Cross-site requests (CSRF to localhost)

**Show**: a POST with a foreign Origin, one without the custom header, and a CORS preflight.
```powershell
'{"username":"x","password":"y"}' | Set-Content -Encoding ascii body.json
curl.exe -i -X POST http://127.0.0.1:8000/api/auth/login -H "Content-Type: application/json" `
  -H "X-Requested-With: NetConfigStudio" -H "Origin: http://evil.example" --data "@body.json"   # 403 Origin not allowed
curl.exe -i -X POST http://127.0.0.1:8000/api/auth/login -H "Content-Type: application/json" `
  -H "Origin: http://127.0.0.1:8000" --data "@body.json"                                          # 403 Missing required request header
curl.exe -i -X OPTIONS http://127.0.0.1:8000/api/jobs -H "Origin: http://evil.example" `
  -H "Access-Control-Request-Method: POST"                                                        # 403, no CORS headers
Remove-Item body.json
```
**Proof:** `pytest tests/security/test_guard.py -k "origin or custom_header or preflight" -v`

**Say:** "Any web page can make my browser send a request to 127.0.0.1. The app needs our Origin *and* a
custom header. A cross-site page can only add a custom header after a CORS preflight, and the app never
answers preflights. The session cookie is also SameSite=Strict."

## 3. Login lockout

**Show**
1. Sign out. Sign in as `demo-view` with a wrong password **5 times**.
2. Sign in with the **right** password. It is still refused, with the same message as a wrong password.
3. Sign in as `demo-admin` → **Audit log**. Filter `auth`: there are five `auth.login denied` entries and one
   `auth.lockout`.
4. Optional: still signed in as `demo-admin`, open `http://127.0.0.1:8000/api/audit/verify` in a new tab.
   `{"ok": true, "first_bad_seq": null}` means the audit hash chain is intact.

**Proof:** `pytest tests/security/test_auth.py -k "lockout or look_the_same or rate_limited" -v`

**Say:** "Five failures lock the account for 15 minutes. The counter is an atomic `$inc` in MongoDB, so
parallel guesses can't race past it. Unknown users and wrong passwords get the same message and take the
same bcrypt time, so nobody can find out which usernames exist."

## 4. Role-based access (RBAC on the server)

**Show**
1. Sign in as `demo-view`. Push and edit buttons are not shown.
2. Show that hiding a button is not the protection. Press F12 → Console and run:
   ```js
   fetch('/api/devices', {method: 'POST', headers: {'X-Requested-With': 'NetConfigStudio',
     'Content-Type': 'application/json'}, body: '{}'}).then(r => r.status)
   ```
   The result is `403`. The server checks the role on every route.
3. Sign out and open `http://127.0.0.1:8000/api/devices`. The result is `401`.

**Proof:** `pytest tests/security/test_auth.py -k "rbac or unauthenticated or lower_roles or unprotected" -v`.
Every route is called anonymously (expects 401) and as each lower role (expects 403). A route missing
from the role table fails the test, and a route without a role check stops the app from starting.

**Say:** "The UI is a convenience; the rule lives on the server. The app refuses to start if a developer adds
an endpoint without a role."

## 5. Command denylist

**Show** (as `demo-eng`, Configure → device → Requirements → *Custom commands*):

| Type | Result in Preview |
|---|---|
| `do rel` | blocked: `'reload' is never sent` (a Cisco abbreviation plus a `do` prefix) |
| `WRITE    erase` | blocked (any case, extra spaces) |
| `description reload-test` | allowed: matching is on whole commands, not words inside them |
| `vlan 10 ; reload` | refused even earlier: input validation does not allow `;`. The denylist would split it too |

**Proof:** `pytest tests/unit/test_safety.py -v` (each blocked and allowed example is one test case)

**Say:** "Matching is on whole commands from the first word, so `no shutdown` or a description containing
'reload' are fine. Abbreviations, `do`, case, spacing and several commands on one line are all caught. It
runs on the final command list, so generated commands are checked too, not only what the user typed."

## 6. Management-interface protection

**Show** (simulation, device with management IP `10.0.0.2`):
1. Custom commands: `interface Vlan1` and `shutdown`. Preview passes, because the app does not know the
   management interface until it talks to the device.
2. Create job → run with any username and password.
3. The job ends **Blocked – nothing was sent**: `'shutdown' is blocked: shuts down the management interface`.
   The transcript shows the pre-check (`show ip interface brief`) and no configuration commands.

**Proof:** `pytest tests/unit/test_safety.py -k management -v` and `pytest tests/push/test_engine.py -k p6 -v`

**Say:** "Before applying, the app finds which interface holds the address it is connected through. Any plan
that shuts it down, changes its IP, moves it to another VLAN or VRF, or removes SSH from the VTY lines is
blocked. If it can't find the interface over SSH, it fails closed."

## 7. SSH host-key pinning (man-in-the-middle protection)

The simulator has no SSH, so show this with the test, or in the lab if one is running.

**Proof:** `pytest tests/push/test_hostkeys.py -v`. The main test,
`test_p14_pin_on_first_use_refuse_on_change_then_accept`, covers:
- the first connection stores the key;
- a different key is refused *during the handshake, before the password is sent*;
- the change shows up for admins and in the audit log (`hostkey.changed`);
- an admin accepts the new key, and the next connection works.

**Lab** (GNS3/CML, `docs/LAB_TESTING.md` L5): on the IOSv router run `crypto key generate rsa modulus 2048`
(answer *yes* to replace the key), then push again. The result is refused, "host key CHANGED". Then go
to **Admin → SSH host keys** → accept, and push again.

**Say:** "Like `known_hosts`, but strict: a changed key is never accepted silently, because that is exactly
what a man in the middle looks like. Only an admin can accept it, and that is audited."

## 8. Rollback

**Proof:**
```powershell
pytest tests/push/test_engine.py -k "p2 or p3 or p4" -v
pytest tests/push/test_sessions.py -k junos -v
```
| Test | Scenario | Expected |
|---|---|---|
| `p2_cli_error_stops_and_rolls_back` | the device answers `% Invalid input` mid-way | stop at that command, `configure revert now`, status `rolled_back` |
| `p3_unreachable_after_apply_relies_on_timer` | the device stops answering after the change | not confirmed, so the device's own revert timer restores it |
| `p4_verification_failure_rolls_back` | a `show` check fails after applying | rolled back and not saved |
| `junos_commit_confirmed_then_confirm_no_save` | Junos | `commit confirmed N`, then `commit` after verification |

**Lab:** `docs/LAB_TESTING.md` L5 (revert timer, verification failure, unreachable after apply).

**Say:** "The change is applied with a safety net the *device* holds: Cisco's archive revert timer or Junos
`commit confirmed`. If my laptop loses the connection, the switch rolls itself back. Only after
verification passes does the app confirm and save."

## 9. Extra checks if there is time

| Control | Proof |
|---|---|
| Device passwords never stored: after a push, open the job in History (and in MongoDB Compass, `jobs`) and search for the password | `pytest tests/push/test_engine.py -k "secrets_scrubbed or running_config_never" -v` |
| Secrets masked in commands, output and backups | `pytest tests/unit/test_masking.py -v` |
| No stack traces to the browser | `pytest tests/security/test_guard.py -k "500 or unhandled" -v` |
| Remote mode needs HTTPS | `$env:HOST="0.0.0.0"; $env:ALLOW_REMOTE="true"; .venv\Scripts\python -m app` refuses to start without `SSL_CERTFILE`/`SSL_KEYFILE` |
| AI prompt injection and secret masking | `pytest tests/api/test_ai.py -k "injection or secrets_never" -v` |
| Audit chain detects tampering | `pytest tests/security/test_auth.py -k chain -v` |
