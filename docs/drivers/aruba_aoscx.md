# HPE Aruba Networking AOS-CX driver reference (`aruba_aoscx`)

Status: **experimental**. Targets CX 6300 / 6100 and the AOS-CX Simulator, releases 10.10–10.15. Researched
2026-11-11 (full notes with every citation and page number: [research/aruba_aoscx.md](research/aruba_aoscx.md),
summary: [research/SUMMARY.md](research/SUMMARY.md)). The driver stays experimental until every **[LAB]**
item below has been checked on the Simulator (`docs/LAB_TESTING.md`, section "Aruba AOS-CX Simulator").

Evidence legend: **V** = text read verbatim in an official HPE guide · **O** = official procedure, exact text
from a search extract · **C** = community source only · **U** = no source retrieved → always **[LAB]**.
AOS-CX has the best evidence of the three: two complete official guides were read –
**[F1010]** *AOS-CX 10.10 Fundamentals Guide, 6300/6400* ([PDF](https://www.bhphotovideo.com/lit_files/1146748.pdf)) and
**[C6100]** *AOS-CX 10.10 CLI Guide, 6000/6100* ([PDF](https://download.axilogi.com/HPE/Manual/HPE_6000_a_6100_MCG.pdf)).

Code: `backend/app/drivers/aruba_aoscx.py` · golden files: `backend/tests/golden/aruba_aoscx/`.

---

## 1. Safe change window – checkpoint auto

| Step | Command (context) | Evidence |
|---|---|---|
| Start the timer | `checkpoint auto <revert_minutes>` (Manager `#`, **before** the changes; 1–60 min) | V – F1010 p.178 |
| Plan commands | `configure terminal` → commands (each line is live at once) → `end` | V |
| Keep the change | `checkpoint auto confirm` | V – F1010 p.178 |
| Roll back | no documented "roll back now": the switch restores the old config when the timer ends | V (timeout path) |
| Save | `write memory` (after the confirm) | V – F1010 p.203 |

- `rollback_strategy()` → `checkpoint`. There is no staging area, so the preview is the only dry run: the
  backend validation carries more weight here. A failed push reports the time at which the switch restores
  its old configuration. Device output to expect: `Auto checkpoint mode expires in N minute(s)`;
  on expiry `WARNING: Restoring configuration. Do NOT add any new configuration.` → `Restoration successful`.
- `revert_minutes` above 60 is refused at review time.
- Netmiko trap: `aruba_aoscx` only recognises `(config)#`, not `(config-if)#`, so the engine sends `end`
  itself before leaving config mode ([research/netmiko.md](research/netmiko.md) Q6).
- Firmware below 10.06.0010 did not revert after the admin disconnected (Aruba community report) – the target
  range is 10.10+.

## 2. Generated commands

| Plan feature | Commands the driver sends | Evidence |
|---|---|---|
| Hostname / domain | `hostname <h>` (1–32 chars) · `ip dns domain-name <d>` | V – F1010 p.333, p.244 |
| Local admin | `user <u> group administrators password plaintext <pw>` (masked in preview, job records and backups) | V – C6100 p.1285 |
| SSH | `ssh server vrf default` · `cli-session` → `timeout <min>` | V – C6100 p.1182, p.232 |
| VLAN | `vlan <id>` → `name <name>` | V – C6100 p.1299 |
| Access port | `interface 1/1/N` → `[description]` → `no shutdown` → `no routing` → `vlan access <id>` → `[spanning-tree port-type admin-edge]` | V – C6100 p.1313, p.707 |
| Trunk | `no routing` → `vlan trunk native <id>` → `vlan trunk allowed <list>` (native **first**: it resets the allowed list to `all`) | V – C6100 p.1315 |
| SVI | `interface vlan <id>` → `ip address A/L` → `no shutdown` | V – F1010 p.74 |
| Routed port | `interface 1/1/N` → `routing` → `ip address A/L` (6300; refused on 6100) | V |
| DHCP server | `dhcp-server vrf default` → `pool <P>` → `range LO HI prefix-len N` → `default-router` → `dns-server` → `exit` → `enable` | O; `default-router` form **[LAB]** |
| Static / default route | `ip route P/L <next-hop>` | V – C6100 pp.1184–1185 |
| OSPF | `router ospf 1` → `router-id` → `area <a>`; per interface `ip ospf 1 area <a>` · `ip ospf passive` | V / O |
| BGP | `router bgp <asn>` → `bgp router-id` → `neighbor X remote-as N` → `address-family ipv4 unicast` → `neighbor X activate` → `network P/L` | O **[LAB]** |

`no routing` is always sent before `vlan access` / `vlan trunk` because the Simulator image is reported to
default ports to routed (community report); it is harmless where it matches the default.

## 3. Refused with a clear error (never skipped)

| Plan option | Reason shown |
|---|---|
| EIGRP | not supported on AOS-CX (no EIGRP in either guide) |
| NAT | not supported on AOS-CX switches (no `ip nat` in either guide) |
| Enable secret | AOS-CX has no enable mode: administrators land at `#` |
| DHCP server, OSPF, BGP, routed ports on a **6100** | HPE: "OSPFv2 is not supported on the 6000 and 6100"; the 6100 guide has no DHCP-server or BGP commands (catalog model `capabilities_exclude`) |
| `login block-for`, banner | no `login block-for`; a banner is typed interactively, not driven yet |
| Enable secret, regenerate SSH keys | no enable mode; AOS-CX creates its own host keys |
| Port security | not built for AOS-CX yet |
| User name not lower case, or `admin`/`root` | AOS-CX user-name rules |
| Hostname > 32 chars, `revert_minutes` > 60, > 4 DNS servers per pool | AOS-CX limits |

## 4. Verification, errors and safety

- Verify: `show running-config` (each section kept), `show vlan`, `show ip ospf neighbors`,
  `show bgp ipv4 unicast summary` **[LAB]**.
- Management interface: found in the running config (`ip address A/L` in-band or `ip static A/L` on the
  out-of-band mgmt port) because `show ip interface brief` is not in the 10.10 guides.
- Error patterns: `Invalid input`, `% Command incomplete`, `Ambiguous command` (V – F1010, REST error table),
  `% Unknown command`, `Error`, `% …` (U **[LAB]**). The `WARNING Please "checkpoint auto confirm"` reminder is
  informational.
- Extra denylist (custom commands): `checkpoint …` (only the engine starts or confirms one), `erase …`,
  `boot …`, `no user`, `zeroize`, and (Phase 5C) `job`, `schedule` and `alias`, which store CLI commands that
  run later.
- Discovery (Phase 4B): `show system` (Product Name, Chassis Serial Nbr), `show lldp neighbor-info detail`
  (V – F1010 p.374, pp.304–307).
