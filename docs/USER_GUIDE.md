# NetConfig Studio – user guide

For network engineers and admins who use the app. Installing it is in the [README](../README.md); how each
safety control works is in [SECURITY.md](SECURITY.md).

## 1. Start and sign in

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
```
The browser opens `http://127.0.0.1:8000`. Sign in with the account an admin created for you. The app runs
only on this PC; nobody else on the network can open it.

- Five wrong passwords lock the account for 15 minutes. The message is the same whether the user name or the
  password was wrong.
- You are signed out after 30 minutes without activity, and after 8 hours at the latest.
- Change your password under your name (top right) → **Your account**. At least 12 characters.

### What each role can do

| | viewer | engineer | admin |
|---|:-:|:-:|:-:|
| See the Overview, Devices, Catalog and History | ✓ | ✓ | ✓ |
| Add and edit devices, read device facts | | ✓ | ✓ |
| Configure: preview, create and run jobs on lab devices | | ✓ | ✓ |
| Request a change to a `production` device | | ✓ | ✓ |
| Approve someone else's production change | | | ✓ |
| Tag a device `production`, manage users, read the audit log, accept SSH host keys | | | ✓ |

Viewers do not see running-config backups.

## 2. Overview

The home page. A **map** of your devices (routers at the top, then Layer 3 switches, switches, access points
and cameras) with links found through LLDP/CDP, plus changes per day, reachable devices and devices by
category. Each chart has **Show as table**. Use the arrow keys to move around the map and Enter to select a
device.

Select a device to see its status. Engineers can **Check status now**, or **read device facts**: enter a
device login once and the app runs only `show` commands to store the model, software version, serial number,
neighbours and VLAN table. The login is not stored. If the device runs a different OS or model than the
inventory says, a warning appears. Fix the inventory before configuring it, because the commands would be
wrong for that OS.

## 3. Add a device

**Devices** → **Add a device**.

1. **Model**: pick category → brand → series → model. The model decides the OS driver and the port names you
   may use. Models marked *unverified* come from sample data; check the port names against the real device.
2. **Management IP**: the address the app connects to. Each address can be used by one device only.
3. **Connection**:
   - **SSH**: the normal choice.
   - **Serial console**: a USB console cable (COM port), for first-time setup.
   - **Lab console (Telnet)**: only for GNS3/CML consoles on loopback or private addresses. It is shown as
     insecure because Telnet sends the password in clear text.
4. **Tags**: `production` turns on the two-person rule (section 6). Only an admin can add or remove it.

Device passwords are **never** saved with the device. You type them each time a job runs.

Access points and cameras are inventory only: their status is checked, nothing is pushed to them. For an
access point, set its uplink switch port and use **Configure switch port** to configure that port.

## 4. Configure a change (5 steps)

**Configure**. The tabs at the top choose a single device or several switches, a **router link** or a
**first-time setup** (section 7).

1. **Device**: an inventory device, *several switches*, or a *catalog model (preview only)* to see what
   commands a model would get without any device.
2. **Requirements**: fill in only the sections you need: hostname and domain, SSH, hardening, VLANs, access
   ports, trunks, SVIs, routed interfaces, DHCP, NAT, static routes, OSPF / EIGRP / BGP. Mistakes are marked
   at the field ("10.0.1.300 is not an address", "the gateway must be inside the pool").
   - **Templates:** **Save as template** keeps the form for next time (never with passwords).
   - **Describe what you need** (only if the AI assistant is on): type a sentence such as "3 departments with
     40 users each, Wi-Fi on VLAN 30, OSPF to the core" and the form is filled in for you. Check every field:
     the draft goes through exactly the same checks as a plan you typed.
   - **Custom commands** (not on production devices): sent exactly as typed after the generated commands.
     They are checked against the same denylist and recorded in the audit log.
3. **Preview**: the exact commands for the device's OS, and the `show` commands used to verify them. A
   feature the OS cannot do is refused here with "… is not supported on …". It is never skipped silently.
   Commands that would cut your own management connection, and dangerous commands (`reload`, `erase`, …), are
   blocked with the reason. **Explain** (AI) describes a command block in plain words.
4. **Create job**: freezes the commands with a hash. Add a change note for the approver and for History.
   Lab devices go straight to *ready*; production devices wait for approval.
5. **Push & verify**: type the device login (and, if the plan creates a local user or an enable secret, those
   passwords twice) and press **Run the push**. Your browser is told not to save these fields. If your
   password manager offers to save them anyway, decline.

### What happens during a push

You see each step live: connecting → backing up → checking → applying → verifying → saving.

- **Connecting:** the device's SSH host key is checked. On the first connection it is stored. If it changes
  later, the push stops **before** your password is sent (section 8).
- **Backing up:** the running configuration is saved with the job, with secrets masked.
- **Checking:** the app finds the interface that holds the management address and blocks the change if it
  would shut it, change its address, move it to another VLAN or remove SSH access.
- **Applying** under a safety timer on the device (Cisco revert timer, Junos `commit confirmed`, EOS session
  timer, AOS-CX checkpoint). The push stops at the first CLI error and shows the exact command.
- **Verifying:** the `show` commands are compared with the plan.
- **Saving:** only after verification passes is the change confirmed and saved.

If anything fails after applying, the device is **rolled back** and the job ends as *rolled back*. If the
laptop loses the connection, the device rolls itself back when its timer runs out. Experimental drivers
without a timer (MikroTik, Huawei, D-Link, TP-Link) cannot roll back by themselves. Restore those from the
backup in the job.

## 5. History

Every job: who asked, who approved, what was sent, what the device answered, the checks and the backup.
Filter by status or kind. In a job:

- **Show the session transcript**: the device output, with passwords and keys masked.
- **Compare with the previous backup**: what changed in the running configuration since the last job on that
  device (and **Explain**, if the AI assistant is on).
- A job can be **withdrawn** by its requester before it runs. For *several switches*, **Stop the remaining
  switches** while it runs.

| Status | Meaning |
|---|---|
| awaiting approval | Production device: waiting for another admin (expires after 24 hours) |
| ready | Approved, or no approval needed. Run it from History or the wizard |
| success | Applied, verified and saved |
| rolled back | Something failed after applying; the old configuration is back |
| failed | Not applied, or partly applied on a multi-switch job (see the summary) |
| blocked | A safety check refused the commands before anything was sent |
| cancelled / expired | Withdrawn, rejected, or not approved in time |

## 6. Production devices: the two-person rule

1. An engineer creates the job. It waits as *awaiting approval*.
2. A **different** admin opens it in History, reads the commands and the change note, and presses
   **Approve** or **Reject** (with a reason). You cannot approve your own request.
3. The requester runs it within 24 hours. The commands are generated again and must match the approved hash
   exactly. If the device, the catalog or the plan changed in the meantime, create a new job.

Custom commands are not allowed on production devices, and production devices need a driver that has passed
lab testing (or `ENABLE_EXPERIMENTAL_DRIVERS=true`).

## 7. More than one device, and new devices

- **Several switches:** the same VLANs and port settings on 2–20 switches, one after another. By default it
  stops at the first failure. If one switch refuses the login, the same login is not tried on the others.
- **Router link:** two routers, their facing ports and a /30 or /31. Both ends get matching addresses and
  routing (OSPF, EIGRP or eBGP). Both sides are applied and verified, then confirmed together. If one side
  fails, the other is rolled back. In the rare case where one side cannot be undone, the job says
  **MANUAL ACTION** and tells you exactly what to do.
- **First-time setup:** for a new device with no SSH yet. Connect a console cable (or a lab console), choose
  the device, and set hostname, management address, gateway, admin user, enable secret and SSH. The app then
  tests an SSH login with the new user; only if it works is the device switched to SSH in the inventory.

## 8. Admin tasks

- **Users:** create accounts (12+ character passwords), change roles, disable accounts. The first admin is
  created on the command line: `.venv\Scripts\python scripts\create_user.py admin --role admin`.
- **Audit log:** every sign-in, user and device change, preview, push, approval and rollback, with who, what,
  when and the result. Filter by action. The log is hash-chained; the banner at the top says "Hash chain intact" or
  shows the first entry that was edited or deleted.
- **SSH host keys:** a red banner means a device offered a different key. Usually the device was replaced
  or its keys were regenerated, but it can also be a man-in-the-middle attack. Compare the new fingerprint
  with the device's own console (`show crypto key mypubkey rsa`, `show ssh server`, …) before you press
  **Accept new key**. **Forget** makes the next connection trust whatever key it is offered; use it only
  for a replaced device.

## 9. When something goes wrong

| You see | Do this |
|---|---|
| "SSH host key of … CHANGED" on a push | An admin checks the fingerprint on the device and accepts it (section 8) |
| "… is not supported on …" | That OS driver cannot do this feature; remove it from the plan |
| "… is blocked: shuts down the management interface" (or "moves the management uplink …") | Change the management interface from its console, or connect over a different interface |
| "% Invalid input" at a command | The device refused that command. The job shows which one, and the device was rolled back |
| *rolled back* after verification | Open the checks: the change applied but the result was not what the plan asked for |
| "A device, the catalog or the plan changed since this job was created" | Create a new job: the approved commands no longer match |
| "Another job is running on one of these devices" | Wait for it to finish (one job per device at a time) |
| "NetConfig Studio is still starting" | MongoDB is not up yet. Start the *MongoDB* Windows service and wait a few seconds |
