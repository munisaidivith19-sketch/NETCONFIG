# Experimental drivers – MikroTik, Huawei VRP, D-Link, TP-Link

These four drivers are **disabled** unless `ENABLE_EXPERIMENTAL_DRIVERS=true` is set in `backend/.env`. When
they are on, the UI labels them "Experimental" and every preview carries an "experimental driver" warning
(production devices still need two-person approval, and custom commands stay disabled on them). Scope is
deliberately small: **hostname, local admin + SSH, VLANs, access ports, trunk ports**. Every other plan
feature is refused with "<feature> is not supported on <OS>". None of them has an automatic rollback.
`rollback_strategy()` → `backup_restore`: a failed push is reported as **MANUAL ACTION**, and the running config
saved with the job is what you restore from.

Researched 2026-11-11 and checked again 2026-11-15. Evidence legend: **V** = text read verbatim in an official
vendor guide · **O** = official page confirms the behaviour, exact text from a secondary source · **C** =
community source only · **U** = no source retrieved → **[LAB]**. Topology discovery (LLDP) is not built for
these drivers.

Code: `backend/app/drivers/experimental/` · golden files: `backend/tests/golden/<os_id>/`.

---

## MikroTik RouterOS v7 (`mikrotik_routeros`) – CRS3xx switches, CHR

RouterOS applies and keeps each command at once (no config mode, no save). VLANs use **bridge VLAN filtering**
on one bridge (driver flag `bridge`, default `bridge`, as in the default configuration).

| Plan feature | Commands | Evidence |
|---|---|---|
| Hostname | `/system identity set name=<h>` | V – manual "Identity" |
| Local admin | `/user add name=<u> group=full password=<pw>` (fails if the user exists; the review warns) | O – manual "User" + examples |
| SSH | `/ip service set ssh disabled=no` · `/ip ssh set strong-crypto=yes` | C (`/ip service set`) **[LAB]**, V (`strong-crypto` property) |
| VLAN + trunk members | `/interface bridge vlan add bridge=<br> vlan-ids=<id> comment=<name> tagged=<trunks>` | V – Bridge VLAN Table |
| Access port | `/interface bridge port set [find interface=<p>] pvid=<id> frame-types=admit-only-untagged-and-priority-tagged ingress-filtering=yes` | V |
| Trunk native VLAN | `… pvid=<native> frame-types=admit-all ingress-filtering=yes` | V (`admit-all` is a listed value) |
| Turn filtering on | `/interface bridge set [find name=<br>] vlan-filtering=yes` – **always last** ("PVID has no effect until VLAN filtering is enabled"; enabling it early can lock you out) | V |

- Verify: `/system identity print`, `/user print terse`, `/interface bridge print terse`,
  `/interface bridge vlan print terse`, `/interface bridge port print terse`. Backup: `/export terse`.
  Management interface: `/ip address print terse`.
- Errors: `failure:`, `bad command name`, `expected end of command`, `syntax error`, `input does not match any
  value`, `no such item`, `invalid value`, `ambiguous value`, `error:` (U **[LAB]**).
- Extra denylist: `system reboot`, `system shutdown`, `system reset-configuration`, …; `remove`/`unset` are blocked
  by the management rules.
- Lab image: MikroTik CHR (free), see `docs/LAB_TESTING.md`.

Sources: [Bridge VLAN Table](https://help.mikrotik.com/docs/spaces/ROS/pages/28606465/Bridge+VLAN+Table) ·
[Bridging and Switching (frame-types, pvid, vlan-filtering)](https://help.mikrotik.com/docs/spaces/ROS/pages/328068/Bridging+and+Switching) ·
[Identity](https://manual.mikrotik.com/docs/7.25/system-information-and-utilities/identity) ·
[User](https://manual.mikrotik.com/docs/7.25/authentication-authorization-accounting/user) ·
[SSH (strong-crypto)](https://help.mikrotik.com/docs/spaces/ROS/pages/132350014/SSH) ·
[Securing your router (/ip/service)](https://manual.mikrotik.com/docs/7.25/getting-started/securing-your-router)

## Huawei VRP (`huawei_vrp`) – S5735-L and other S-series campus switches (V200)

`system-view` → commands (sub-views end with `quit`) → `return`; `save` asks `[Y/N]` and is answered `y`. VRP
negates with `undo`, which the safety checks treat like `no`.

| Plan feature | Commands | Evidence |
|---|---|---|
| Hostname | `sysname <h>` | U **[LAB]** |
| Local admin | `aaa` → `local-user <u> password irreversible-cipher <pw>` → `local-user <u> privilege level 15` → `local-user <u> service-type ssh` | O – V200R011C10 Basic Configuration (shown for telnet/web users) **[LAB]** |
| SSH | `stelnet server enable` · `ssh user <u>` · `ssh user <u> authentication-type password` · `ssh user <u> service-type stelnet` · `user-interface vty 0 4` → `authentication-mode aaa` → `protocol inbound ssh` → `idle-timeout <m> 0` | O – S310 / CloudEngine S5700 guides |
| VLAN | `vlan <id>` → `name <name>` → `quit` | U **[LAB]** |
| Access port | `port link-type access` · `port default vlan <id>` · `[stp edged-port enable]` | U **[LAB]** |
| Trunk | `port link-type trunk` · `port trunk allow-pass vlan <ids>` (≤ 10 items per command) · `undo port trunk allow-pass vlan 1` · `port trunk pvid vlan <native>` | V (`allow-pass`), O (`pvid`; Huawei AP reference) |

- Verify: `display current-configuration`. Management interface: `display ip interface brief`.
  Discovery: `display version`, `display esn`.
- Errors: `Error:`, `Unrecognized command`, `Incomplete command`, `Wrong parameter`, `Too many parameters`,
  `Ambiguous command` (U **[LAB]**).
- Extra denylist: `reboot`, `reset saved-configuration`, `startup …`, `undo local-user`, `undo aaa`,
  `undo user-interface`, `rsa local-key-pair destroy`.
- No free lab image is listed in CLAUDE.md; test on a real switch or eNSP before promoting.

Sources: [S1720/S2700/S5700/S6720 V200R011C10 Ethernet Switching (trunk examples)](https://support.huawei.com/enterprise/en/doc/EDOC1000178168/cbf869f6/example-for-configuring-dot1q-termination-sub-interfaces-to-implement-inter-vlan-communication) ·
[`port trunk pvid vlan` (Huawei AP V200R019C00 command reference)](https://support.huawei.com/enterprise/en/doc/EDOC1100096311/299a5aeb/port-trunk-pvid-vlan) ·
[`port link-type`](https://support.huawei.com/enterprise/en/doc/EDOC1100096311/5661a2d6/port-link-type) ·
[V200R011C10 Basic Configuration – local-user irreversible-cipher](https://support.huawei.com/enterprise/en/doc/EDOC1000178166/dbec5988/configuring-a-web-user-and-logging-in-to-the-web-system) ·
[S310 – SSH server (`stelnet server enable`)](https://support.huawei.com/enterprise/en/doc/EDOC1100306153/379d8aea/configuring-the-ssh-server-function-and-related-parameters) ·
[CloudEngine S5700 – STelnet login troubleshooting (`protocol inbound ssh`, `ssh user`)](https://support.huawei.com/enterprise/en/doc/EDOC1100278277/fe935bb6/failed-to-log-in-to-the-ssh-server-using-stelnet)

## D-Link DGS-1210 Smart Managed (`dlink_ds`)

No configuration mode: every command runs at the main prompt and applies at once; `save` writes NV-RAM. Ports
are plain numbers and port lists use ranges (`1-3,5`). Source: *DGS-1210 Ver.R1 Smart Ethernet Managed Switch
CLI Reference Guide V1.0* (D-Link, 2020) – page numbers below are the guide's own. **Note:** the DGS-1210/**ME**
(Metro) guides use different syntax (`config gvrp <ports> pvid`, interactive `config account`); this driver
targets the R1 Smart CLI only.

| Plan feature | Commands | Evidence |
|---|---|---|
| Hostname | `config snmp system_name <h>` (≤ 32 chars) | V – p.75 |
| Local admin | `config account <u> encrypt plain_text <pw>` (≤ 15 chars; the account must already exist – `create account` asks interactively and is denied) | V |
| Password encryption | `enable password encryption` | V |
| SSH | `enable ssh` | V – p.26 |
| VLAN | `create vlan <name> tag <id>` (name ≤ 20 chars) – an existing VLAN is renamed with `config vlan vlanid <id> name <name>` | V – p.142 |
| Access / trunk membership | `config vlan vlanid <id> add untagged|tagged <ports>` | V |
| PVID | `config port_vlan <ports> pvid <id>` | V – p.146 |

- Verify: `show switch`, `show vlan`, `show port_vlan pvid` (also checks access ports left VLAN 1).
  Backup: `show config current_config`. Management interface: `show ipif` + `show vlan`.
- Errors: `Fail`, `Next possible completions`, `Available commands`, `ERROR`, `Invalid`, `does not exist`,
  `already exist` (U **[LAB]**).
- Extra denylist: `reboot`, `reset`, `download`, `upload`, `config firmware`, `create account`.

Sources: [DGS-1210 R1/R2 CLI Manual v1.00 (D-Link FTP)](https://ftp.dlink.ru/pub/Switch/DGS-1210-26_FL/Description/DGS-1210_Series_R1_R2_CLI_Manual_v1.00(WW)(press)%20(1).pdf) ·
for comparison, the Metro guide: [DGS-1210/ME B1 CLI Reference v2.53](https://ftp.dlink.ru/pub/Switch/DGS-1210-52P_ME/Firmware/DGS-1210ME%20Series_B1_CLI%20Reference%20Guide_v2.53(WW).pdf)

## TP-Link JetStream / Omada (`tplink_jetstream`) – TL-SG2000/3000, T1600G/T2600G

`configure` → commands → `end` (Netmiko leaves one `exit` at a time, so `end` is sent first). Source:
*JetStream L2 Managed Switch CLI Reference Guide, TL-SG3210/3216/3424/3424P, REV3.0.1* (TP-Link).

| Plan feature | Commands | Evidence |
|---|---|---|
| Hostname | `hostname <h>` (1–32 chars) | V – p.119 |
| Local admin | `user name <u> privilege admin secret 0 <pw>` | V – p.52 |
| SSH | `ip ssh server` · `ip ssh version v2` | V – p.103 |
| VLAN | `vlan <id>` → `name <name>` → `exit` | V |
| Access port | `interface gigabitEthernet 1/0/N` → `switchport general allowed vlan <id> untagged` → `switchport pvid <id>` → `no switchport general allowed vlan 1` | V – pp.28–29 |
| Trunk | `switchport general allowed vlan <list> tagged` · `switchport general allowed vlan <native> untagged` · `switchport pvid <native>` | V |
| Save | `copy running-config startup-config` | V – p.123 |

- Verify and backup: `show running-config`. Discovery: `show system-info`.
- Errors: `Error`, `% …`, `Bad command`, `Invalid`, `Incomplete command` (U **[LAB]**).
- Extra denylist: `reboot`, `reset`, `firmware`, `boot`, `no user`, `no ip ssh`.

Sources: [TL-SG3424 CLI Reference Guide (PDF)](https://static.tp-link.com/res/down/doc/TL-SG3424(UN)_V2.0_CLI.pdf) ·
[Typical CLI Configuration Examples for TP-Link JetStream Switch](https://www.tp-link.com/support/faq/3534)

---

## Promoting an experimental driver

1. Run the lab checklist for that OS (`docs/LAB_TESTING.md`) and replace each **[LAB]** golden fixture with real
   output.
2. Move it from `EXPERIMENTAL` to `CORE` in `backend/app/drivers/registry.py`, and change its catalog support
   level only after the author confirms the lab results.
