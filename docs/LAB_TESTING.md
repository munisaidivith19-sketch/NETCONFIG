# Lab testing – Cisco IOSv / IOSvL2 in GNS3 or CML-Free

The automated tests prove the **app** (validation, safety rules, push flow, rollback logic) with a fake
device. They cannot prove that the **commands** are right for a real IOS image. This checklist does that.
The Cisco IOS driver stays `experimental` until every item below has passed and is recorded in the
results table at the end (`docs/TEST_PLAN.md` section 8).

> Use an isolated lab. Telnet consoles send passwords in clear text, and the tests deliberately break
> the configuration.

## 1. What you need (all free)
| Item | Notes |
|---|---|
| GNS3 2.2 (GUI + GNS3 VM) **or** Cisco Modeling Labs – Free | either one works |
| IOSv (router) and IOSvL2 (switch) images | included with CML-Free; for GNS3 you need your own licensed images |
| Windows loopback adapter ("Microsoft KM-TEST Loopback Adapter") | lets the laptop reach the lab over SSH |
| NetConfig Studio running normally (not simulation mode) | `cd backend; .venv\Scripts\python -m app` |

## 2. Topology
```
                 laptop (NetConfig Studio, 127.0.0.1:8000)
                   │ loopback adapter 10.0.0.100/24
                   │
              [ Cloud / External connector ]
                   │
               SW1 (IOSvL2)  Gi0/0 ── mgmt VLAN 1, 10.0.0.2/24
                   │ Gi0/1 trunk
               SW2 (IOSvL2)  Vlan1 10.0.0.3/24
                   │ Gi0/2 (VLAN 1)
      ┌────────────┴────────────┐
   R1 (IOSv) Gi0/0 10.0.0.11    R2 (IOSv) Gi0/0 10.0.0.12
      Gi0/1 ──────── link ────── Gi0/1          (the router link wizard sets 10.255.0.0/30)
```
- **GNS3:** add a *Cloud* node bound to the loopback adapter and connect it to SW1 Gi0/0. Give the
  loopback adapter `10.0.0.100/24` in Windows network settings.
- **CML-Free:** use an *External Connector* in bridge mode to the loopback adapter. For consoles, run the
  CML **Breakout Tool**: it publishes every node console on a localhost Telnet port.
- Start all four nodes with **no startup configuration**: they boot into the initial configuration
  dialog, which is exactly what first-time setup has to handle.

## 3. Add the devices to the inventory
In **Devices → Add device**:

| Name | Model | Management IP | Connection |
|---|---|---|---|
| sw1 | Cisco IOSvL2 | `127.0.0.1` | Lab console, port = SW1's console port (GNS3: right-click → *Console port*, e.g. 5000) |
| sw2 | Cisco IOSvL2 | `127.0.0.1` | Lab console, port of SW2 |
| r1 | Cisco IOSv | `127.0.0.1` | Lab console, port of R1 |
| r2 | Cisco IOSv | `127.0.0.1` | Lab console, port of R2 |

(Only one device can own an address, so give each console a different loopback address – `127.0.0.1`,
`127.0.0.2`, … all reach the same GNS3 server – or add them one at a time.) With a real switch and a USB
console cable, choose **Serial console** and the COM port shown in Windows Device Manager.

## 4. Checklist

Write the date, image version and result for every row in the results table (section 5).

### L1 – First-time setup over the console (Configure → First-time setup)
1. Choose `sw1`. Hostname `sw1`, domain `lab.example.net`, admin user `netadmin`, management VLAN `1`,
   address `10.0.0.2/24`, gateway `10.0.0.1` (none needed in this lab, but it tests the command).
2. Preview: check `hostname`, `ip domain name`, `interface Vlan1`, `ip address 10.0.0.2 255.255.255.0`,
   `ip default-gateway 10.0.0.1`, `crypto key generate rsa modulus 2048`, `ip ssh version 2`,
   `line vty 0 4` / `transport input ssh`.
3. Create the job and run it with **no device login** (a fresh console has none). Enter the new admin
   password and enable secret.
4. Expected: the job gets past *connecting* without hanging (Netmiko answers the dialog with `no` and
   presses RETURN through "terminate autoinstall? [yes]"; this happens during login, so it is not in the
   transcript – watch the console in GNS3 to see it); the job is `success`; the check
   *SSH login to 10.0.0.2 as netadmin* passes; the device is now SSH (Devices page) and its host key is
   listed under **Admin → SSH host keys**.
5. Repeat for `sw2` (`10.0.0.3`) and, with **Management interface** `GigabitEthernet0/0`, for `r1`
   (`10.0.0.11`) and `r2` (`10.0.0.12`). For routers the gateway becomes `ip route 0.0.0.0 0.0.0.0 …`.
6. Negative: run L1 again with the laptop unplugged from the lab (disable the loopback adapter). Expected:
   setup saved, SSH check fails, the device **stays** on its console connection.

**[LAB] items confirmed here:** the IOSv archive filesystem (`flash0:`), the RSA prompt handling, the
dialog / "Press RETURN" handling and, on IOSvL2, that `ip default-gateway` is accepted.

### L2 – Every golden case on a real device (Configure → Device change)
For each file in `backend/tests/golden/cisco_ios/*.json`, build the same plan in the wizard for a matching
device (switch cases on `sw1`, routing cases on `r1`), push it, and check:
- the job is `success` and every *required* check passes;
- `show running-config` on the device contains exactly the previewed lines.
Note any command the device rewrites (for example abbreviations it expands) – that is a driver bug to fix
before marking the driver `tested`.

### L3 – Several switches (Configure → Device change → Several switches)
1. Pick `sw1` and `sw2`, add VLANs 10 *Sales* and 20 *Staff*, push. Expected: both steps `success`,
   summary "2 of 2 devices changed".
2. Stop on failure: suspend the link to `sw1` in GNS3 / CML so it is unreachable, then push VLAN 30 to
   both. Expected: `sw1` fails at *connecting*, `sw2` is **not started** (cancelled, "stop on failure").
   Untick *Stop at the first switch that fails* and repeat: `sw2` is changed, the job is `failed` with
   "1 of 2 devices changed".

### L4 – Router link (Configure → Router link)
1. A = `r1` Gi0/1, B = `r2` Gi0/1, subnet `10.255.0.0/30`, OSPF area 0, router IDs `1.1.1.1` / `2.2.2.2`.
2. Expected preview checks: same subnet, different addresses, same area, different router IDs.
3. Run. Expected: both sides `success`; on R1 `show ip ospf neighbor` shows 2.2.2.2 **FULL** within about a
   minute (the in-app neighbour check is informational, because the neighbour may still be coming up).
4. Repeat with eBGP (AS 65001 / 65002) and `show ip bgp summary` → Established; and with a `/31`.
5. Failure on B: suspend R2's management link (R2–SW2) in GNS3 / CML, then run a new link job. A is
   applied and verified first; B cannot connect. Expected: B `failed`, **A `rolled_back`**
   (`configure revert now` in A's transcript), and R1's Gi0/1 has no `10.255.0.1` afterwards
   (`show ip interface brief`).

### L5 – Rollback paths
1. CLI error mid-way: add a custom command `interface GigabitEthernet9/9` on a lab device. Expected:
   `rolled_back`, error names that command, nothing after it was sent, `show archive log config all`
   shows the revert.
2. Unreachable after apply: suspend the management link while the job is *applying*. Expected: job
   `rolled_back` with "device unreachable"; after the revert timer the device has its old config back
   (`show running-config`).
3. Revert timer: `configure terminal revert timer 10` → `show archive config rollback timer` shows the
   pending timer **[LAB]**.

### L6 – Safety rules on a real device
1. A plan that moves `Vlan1` (the management SVI) to another address over SSH → **blocked**, nothing sent.
2. Custom command `reload` / `do rel` → **blocked**.
3. Regenerate SW1's SSH key (`crypto key generate rsa modulus 2048` on its console), then push. Expected:
   refused, "host key CHANGED"; an admin accepts the new key in **Admin → SSH host keys**; the next push works.

### L7 – Approval flow
Tag `r1` `production` (as admin), create a router link job as an engineer → `awaiting_approval`; the same
engineer cannot approve; a second admin approves; the engineer runs it. Expected: audit log shows
`job.create`, `job.approve`, `job.run`, `job.finish` with the same commands hash.

## 5. Results
| Date | Item | Emulator / image | Result | Notes |
|---|---|---|---|---|
| | L1 sw1 / sw2 / r1 / r2 | | | |
| | L1 negative (no SSH reachability) | | | |
| | L2 golden cases (list) | | | |
| | L3 multi-switch | | | |
| | L4 link OSPF / BGP / /31 / B fails | | | |
| | L5 rollback paths | | | |
| | L6 safety rules | | | |
| | L7 approval | | | |

When every row passes, set `support: "tested"` for `cisco_ios` in `backend/app/data/catalog.json`, run
`scripts/seed_catalog.py`, and record the change in the README progress table.
