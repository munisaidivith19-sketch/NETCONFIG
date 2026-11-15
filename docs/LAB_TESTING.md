# Lab testing

Part A covers Cisco IOSv / IOSvL2 (GNS3 or CML-Free). Part B (section 6 onward) covers the Phase 4
drivers: Arista cEOS-lab, Juniper vJunos, the Aruba AOS-CX Simulator and MikroTik CHR.

# Part A – Cisco IOSv / IOSvL2 in GNS3 or CML-Free

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

---

# Part B – Phase 4 drivers (Arista, Juniper, Aruba, MikroTik)

Every Phase 4 driver is `experimental`. Its reference page (`docs/drivers/<os_id>.md`) marks each command
that was not read verbatim in vendor documentation with **[LAB]**. This part of the checklist proves those
items. A driver is promoted to `tested` only after **the author** confirms that every row of its results
table passed. Claude Code must not change the support level on its own.

## 6. Images and common setup (all free)

| OS | Image | How to get it | Runs in |
|---|---|---|---|
| Arista EOS | **cEOS-lab** 4.3x (container) | free arista.com account → Software Downloads → cEOS-lab | GNS3 VM (Docker template) or containerlab in WSL2 |
| Juniper Junos | **vJunos-switch** (EX ELS) and **vJunos-router**; for SRX NAT use the vSRX 3.0 evaluation | free download from juniper.net ("vJunos labs") | GNS3 VM (QEMU, 4 GB RAM, KVM needed) |
| Aruba AOS-CX | **AOS-CX Simulator** 10.10+ (OVA) | free HPE Networking Support Portal account | GNS3 VM (QEMU) or VirtualBox |
| MikroTik | **CHR** 7.x (raw disk image) | mikrotik.com/download; the free 1 Mbit/s licence is enough | GNS3 VM (QEMU) |

NetConfig Studio itself still uses no Docker. The cEOS container runs only inside the GNS3 VM or WSL2.

Topology (reuses the loopback adapter `10.0.0.100/24` from section 2):
```
laptop 10.0.0.100 ── Cloud ── mgmt switch (IOSvL2 or a GNS3 Ethernet switch, VLAN 1)
                                 ├── ceos1    Management0      10.0.0.21/24
                                 ├── vjunos1  fxp0 / em0       10.0.0.31/24   ge-0/0/0 ── ge-0/0/0 vjunos2 (10.0.0.32)
                                 ├── cx1      mgmt (VRF mgmt)  10.0.0.41/24   1/1/1 ── 1/1/1 cx2 (10.0.0.42)
                                 └── chr1     ether1           10.0.0.51/24
```
First-time setup is **not** automated for these OSes. Netmiko 4.8.0 has no serial driver for any of them and
no telnet driver for AOS-CX (`docs/drivers/research/netmiko.md` Q1). On each node's console, set its
management address and an admin user by hand. Then add it in **Devices → Add device** with connection **SSH**:

| Name | Model | Management IP |
|---|---|---|
| ceos1 | Arista cEOS-lab | 10.0.0.21 |
| vjunos1 / vjunos2 | Juniper vJunos-switch | 10.0.0.31 / .32 |
| cx1 / cx2 | Aruba AOS-CX Simulator | 10.0.0.41 / .42 |
| chr1 | MikroTik CHR (needs `ENABLE_EXPERIMENTAL_DRIVERS=true`) | 10.0.0.51 |

Common items for **every** OS (record each one in that OS's results table):
- **P1 Golden cases.** For each `backend/tests/golden/<os_id>/*.json` that has a `.txt` file, build the same
  plan in the wizard and push it. The job must end `success`, and the device must show exactly the previewed
  lines. Copy the real output of each verify command into `backend/tests/golden/<os_id>/outputs/`, so the
  checks are tested against real text.
- **P2 Refused features.** The preview must refuse each `.json` case that has **no** `.txt` (for example
  `eigrp_named_or_classic`) with a clear "not supported" message.
- **P3 CLI error.** A custom command with a typo (for example `interfase Ethernet1`) gives `rolled_back` (on
  Junos: `failed` with nothing applied), and the error names that command. Write the exact error text in the
  notes and compare it with the driver's `ERROR_PATTERNS`.
- **P4 Unreachable after apply.** Suspend the node's management link while the job is *applying*. Expected:
  the device's own timer restores the old configuration (check after the timer runs out).
- **P5 Safety.** A plan that changes the management address is **blocked**. So is each OS-specific denylisted
  custom command (see "Extra denylist" on each driver page).
- **P6 Discovery (Phase 4B).** On the device panel, **Read device facts** with a device login fills in model,
  version and serial, and the LLDP links appear on the Overview topology map.

## 7. Arista cEOS-lab (`arista_eos`)

| # | Check | Expected |
|---|---|---|
| A1 | Session flow: push `vlans_multi` and watch the transcript | `configure session nc-…` → commands → `commit timer 00:10:00` → verify → `configure session nc-… commit` → `copy running-config startup-config` |
| A2 | During a push, run `show configuration sessions detail` on the console | the session is `pendingCommitTimer`; after the confirm it is `completed` |
| A3 | Roll back now: force a failed verification | `configure session <name> abort` is accepted. If EOS refuses it, write down the reply; the timer must still restore the config |
| A4 | What `end` does inside a session (type it by hand in a test session) | write down whether it commits, keeps the session pending, or prompts |
| A5 | Every U line on `docs/drivers/arista_eos.md` (hostname, `dns domain`, switchport, SVI + `ip routing`, OSPF, BGP, `dhcp server ipv4` on the SVI) | accepted as typed, and shown the same way in `show running-config` |
| A6 | NAT golden case | write down whether cEOS accepts `ip nat source dynamic … overload` (hardware dependent) |
| A7 | Leave a session pending by hand (`max pending` = 1), then push | refused with a clear error; nothing applied |

## 8. Juniper vJunos-switch / vJunos-router (`juniper_junos`)

| # | Check | Expected |
|---|---|---|
| J1 | Commit flow: push `vlans_multi` | `configure private` → `set …` → `commit check` (`configuration check succeeds`) → `commit confirmed 10` → verify → `commit` (`commit complete`) |
| J2 | A typo in a custom `set` command | refused **before** commit; `show system commit` has no new entry; job `failed` with "nothing was applied" |
| J3 | Failed verification after `commit confirmed` | `rollback 1` + `commit` restore the old config; `show system commit` shows both commits |
| J4 | Unreachable after `commit confirmed` (P4) | after 10 minutes Junos rolls back on its own (`show system commit` shows the rollback) |
| J5 | Admin user from the `ssh_v2` case | the `$6$` hash from `shacrypt.py` lets `netadmin` log in with the plan's password |
| J6 | `set system services ssh protocol-version v2` | accepted or refused on this release: write it down |
| J7 | Trunk + native VLAN (`trunk_allowed_native`) | `show ethernet-switching interface` shows the members and the native VLAN |
| J8 | IRB + DHCP (`dhcp_pool_excluded`) | a client in the VLAN gets an address; `show dhcp server binding` lists it |
| J9 | NAT on vSRX (`nat_overload_acl`) | traffic from trust leaves with the interface address; on vJunos-switch the case is refused |
| J10 | The exit prompt text in private mode | write down the exact wording (Netmiko answers "yes" to it; the engine never leaves before the commit) |

## 9. Aruba AOS-CX Simulator (`aruba_aoscx`)

| # | Check | Expected |
|---|---|---|
| X1 | Checkpoint flow: push `vlans_multi` | `checkpoint auto 10` (`Auto checkpoint mode expires in 10 minute(s)`) → `configure terminal` → commands → `end` → verify → `checkpoint auto confirm` (`checkpoint AUTO… created`) → `write memory` (`Success`) |
| X2 | Failed verification | the job reports when the switch will restore the old config. After the timer: `Restoration successful` on the console, and the old config is back |
| X3 | Unreachable after apply (P4) | same as X2: the switch restores the config on its own |
| X4 | Default port mode on the Simulator | write down whether ports start routed; `no routing` before `vlan access` must be accepted either way |
| X5 | Trunk order (`trunk_allowed_native`) | after `vlan trunk native 99` + `vlan trunk allowed 10,20,99`, `show interface 1/1/N` lists only those VLANs (not `all`) |
| X6 | DHCP server (`dhcp_pool_excluded`) | the `default-router` and `lease` lines are accepted as generated; a client gets an address |
| X7 | 6100 model rules | with the 6100 model chosen in the wizard, DHCP, OSPF, BGP and routed ports are refused |
| X8 | `checkpoint rollback` while auto mode is active (by hand) | write down whether it is allowed (this decides whether a faster "roll back now" can be added) |

## 10. MikroTik CHR (`mikrotik_routeros`, experimental)

| # | Check | Expected |
|---|---|---|
| M1 | `vlans_access_trunk` on a bridge with ether2–ether4 | VLAN filtering is switched on **last**, and the SSH session survives |
| M2 | `basic_ssh` | `/system identity`, the new user and `/ip ssh strong-crypto=yes` are set |
| M3 | Failure | the job ends as **MANUAL ACTION** with the backup (`/export terse`) attached |

## 11. Results – Part B

| Date | OS / image | Items | Result | Notes (error texts, refused lines) |
|---|---|---|---|---|
| | cEOS-lab | P1–P6, A1–A7 | | |
| | vJunos-switch | P1–P6, J1–J8, J10 | | |
| | vSRX | J9 | | |
| | AOS-CX Simulator | P1–P6, X1–X8 | | |
| | MikroTik CHR | P1–P5, M1–M3 | | |

When every row for an OS passes, tell Claude Code which rows passed. It then updates the golden outputs,
removes the **[LAB]** marks from that driver page, and sets `support: "tested"` in `catalog.json`.
