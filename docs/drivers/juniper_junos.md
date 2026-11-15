# Juniper Junos driver reference (`juniper_junos`)

Status: **experimental**. Targets EX switches and vJunos-switch (ELS syntax) and SRX / vJunos-router
(catalog category `router`). Researched 2026-11-11 (full notes with every citation:
[research/juniper_junos.md](research/juniper_junos.md), summary: [research/SUMMARY.md](research/SUMMARY.md)).
The driver stays experimental until every **[LAB]** item below has been checked on vJunos
(`docs/LAB_TESTING.md`, section "Juniper vJunos-switch / vJunos-router").

Evidence legend: **V** = text read verbatim on an official Juniper page · **O** = official procedure, exact text
from a secondary source · **C** = community source only · **U** = no source retrieved → always **[LAB]**.
Juniper's documentation now redirects to `networkingdocs.hpe.com`; the links keep the canonical juniper.net path.

Code: `backend/app/drivers/juniper_junos.py` · golden files: `backend/tests/golden/juniper_junos/`.

---

## 1. Safe change window – private candidate + commit confirmed

| Step | Command | Evidence |
|---|---|---|
| Enter staging | `configure private` – a private candidate; nothing is live until commit | O |
| Plan commands | `set …` lines (every command is a full statement; no sub-modes) | – |
| Syntax check | `commit check` – checks the candidate without activating it | V |
| Arm the timer | `commit confirmed <revert_minutes>` (1–65 535, default 10) – allowed in private mode since 11.4 | V |
| Keep the change | `commit` (inside `configure private` again) | V |
| Discard before arming | `rollback 0` | O |
| Roll back now | `rollback 1` → `commit` (inside `configure private`) | U **[LAB]** |
| Save | none – a commit is already persistent (`save_command()` → `None`) | O |

- `rollback_strategy()` → `commit_confirmed`. A refused line or a failed `commit check` means **nothing was
  applied**: the engine discards the candidate and reports the exact command.
- Netmiko trap: `exit_config_mode()` answers "yes" to "Exit with uncommitted changes?", which silently throws
  the candidate away. The engine never leaves config mode before the commit
  ([research/netmiko.md](research/netmiko.md) Q4).
- Netmiko's `commit()` decides success by marker strings (`commit complete`,
  `configuration check succeeds`, `commit confirmed will be automatically rolled back in`) **[LAB: confirm on
  vJunos]**.

Sources: [Juniper `commit` reference](https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/command/commit.html) ·
[Overview of the configure command](https://www.juniper.net/documentation/us/en/software/junos/cli/topics/topic-map/configure-command.html) ·
[Juniper `rollback` reference](https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/command/rollback.html)

## 2. Generated commands

| Plan feature | Commands the driver sends | Evidence |
|---|---|---|
| Hostname / domain | `set system host-name <h>` · `set system domain-name <d>` | U **[LAB]** |
| Banner | `set system login message "<text>"` | U **[LAB]** |
| Local admin | `set system login user <u> class super-user` · `… authentication encrypted-password "<$6$ hash>"` | O |
| SSH | `set system services ssh protocol-version v2` | U **[LAB]** (keyword depends on release) |
| VLAN | `set vlans <name> vlan-id <id>` | C / O |
| Access port | `set interfaces <if> unit 0 family ethernet-switching interface-mode access` · `… vlan members <id>` | V |
| Edge port | `set protocols rstp interface <if> edge` | O |
| Trunk | `… interface-mode trunk` · one `… vlan members <id>` line per VLAN · `set interfaces <if> native-vlan-id <id>` (the native VLAN must also be a member) | O / U **[LAB]** |
| IRB (SVI) | `set interfaces irb unit <id> family inet address A/L` · `set vlans <name> l3-interface irb.<id>` | C / O |
| Routed port | `set interfaces <if> unit 0 family inet address A/L` | U **[LAB]** |
| DHCP server | `set access address-assignment pool <P> family inet network …` · `range R1 low/high` · `dhcp-attributes router / name-server / maximum-lease-time` · `set system services dhcp-local-server group <P> interface <irb.N>` | V (pool, group), U (`name-server`) **[LAB]** |
| NAT (SRX only) | `set security nat source rule-set NCS-NAT from zone trust` / `to zone untrust` · `rule NCS-NAT-OUT match source-address …` · `then source-nat interface` + a trust→untrust policy `NCS-ALLOW-OUT` | V (NAT), U (policy lines) **[LAB]** |
| Static route | `set routing-options static route P/L next-hop <nh>` | U **[LAB]** |
| OSPF | `set routing-options router-id <id>` · `set protocols ospf area <a> interface <if>.0 [passive]` | U **[LAB]** |
| BGP | `set routing-options autonomous-system <asn>` · group `NCS-EBGP` `type external`, `peer-as`, `neighbor` · export policy `NCS-BGP-EXPORT` for the advertised networks | U **[LAB]** |

**Password hash.** Junos `plain-text-password` asks for the password interactively, and a plain password put
into `encrypted-password` locks the account. The driver therefore computes a SHA-512-crypt (`$6$`) hash itself
(`backend/app/security/shacrypt.py`, because Python's `crypt` module does not exist on Windows) and sends
`encrypted-password "<hash>"`. The preview shows `********`; the hash is also masked in job records.

## 3. Refused with a clear error (never skipped)

| Plan option | Reason shown |
|---|---|
| EIGRP | "EIGRP is not supported on Juniper Junos" (Cisco protocol) |
| NAT on EX / vJunos-switch | NAT exists only on SRX (catalog model `capabilities_exclude`) |
| Enable secret, regenerate SSH keys | Junos has no enable mode (the login class gives the rights) and creates its own host keys |
| Port security | not built for Junos yet |
| `login block-for` | Junos uses `login retry-options` instead; not built yet |
| Turn off J-Web | needs a `delete` command, which the denylist blocks |
| VLAN named `default`; IRB or DHCP for a VLAN/subnet not in the plan | Junos links the IRB to the VLAN by name |
| Different router IDs for OSPF and BGP | Junos has one `routing-options router-id` |
| Custom commands that are not `set …` statements | only `set` lines are allowed in the private candidate |

## 4. Verification, errors and safety

- Verify: `show configuration | display set` (every `set` line kept), `show interfaces terse`,
  `show ospf neighbor`, `show bgp summary` – U **[LAB: freeze real output]**.
- Management interface: the logical interface in `show interfaces terse` whose address is the management IP.
- Error patterns: `syntax error`, `error:`, `unknown command`, `missing argument`, `invalid value`,
  `is ambiguous`, `commit failed`, `configuration check-out failed`, `not within range`, `invalid interface`
  (U **[LAB]**). `warning:` lines are informational.
- Extra denylist (custom commands): `commit`, `rollback`, `load`, `deactivate`, `exit`, `quit`, `top`, `edit`,
  `request`, `run`, `replace`, `rename`, `copy`, `insert`, `wildcard`. A bare `delete` is already denied
  globally (CLAUDE.md 8.5).
- Discovery (Phase 4B): `show version`, `show chassis hardware`, `show lldp neighbors` (U **[LAB]**).
