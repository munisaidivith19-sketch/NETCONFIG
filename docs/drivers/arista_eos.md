# Arista EOS driver reference (`arista_eos`)

Status: **experimental**. Researched 2026-11-11 (full notes with every citation:
[research/arista_eos.md](research/arista_eos.md), summary: [research/SUMMARY.md](research/SUMMARY.md)).
The driver stays experimental until every **[LAB]** item below has been checked on cEOS-lab
(`docs/LAB_TESTING.md`, section "Arista cEOS-lab").

Evidence legend: **V** = text read verbatim on an official Arista page · **O** = official procedure, exact text
from a secondary source · **C** = community source only · **U** = no source retrieved (candidate syntax) →
always **[LAB]**. EOS has the weakest evidence of the three Phase 4 OSes: arista.com returned HTTP 403 for most
manual pages, so most basic syntax is U and must be proven on cEOS-lab first.

Code: `backend/app/drivers/arista_eos.py` · golden files: `backend/tests/golden/arista_eos/`.

---

## 1. Safe change window – configuration session + commit timer

| Step | Command (mode) | Evidence |
|---|---|---|
| Enter staging | `configure session <name>` (privileged EXEC). `<name>` is short (`nc-<8 hex>`): the prompt shows only six characters. | V |
| Plan commands | typed into the session; nothing is live yet (`applies_immediately=False`) | V |
| Arm the timer | `commit timer hh:mm:ss` (session mode) – commits now and rolls back by itself unless confirmed | V |
| Keep the change | `configure session <name> commit` (EXEC) | C **[LAB]** |
| Discard before arming | `abort` (session mode) | V |
| Roll back now | `configure session <name> abort` | U **[LAB]** – if refused, the timer still restores the old config |
| Save | `copy running-config startup-config` (sent after the confirm only) | U **[LAB]** |

- `rollback_strategy()` → `session_timer`. A lost connection after arming is safe: EOS restores
  `commitTimerCheckPointConfig` when the timer ends.
- A commit **replaces** the running config with the session copy, so two pushes to one switch must never
  overlap. The job runner already allows one push per device at a time.
- Uncommitted sessions are lost on reboot and time out after 24 h. `service configuration session max pending`
  defaults to 1, so a stuck session blocks the next push – the lab checklist covers clearing one.
- Never use `service configuration session commit … save startup-config`: it saves before verification.

Sources: [EOS Session Management Commands](https://www.arista.com/en/um-eos/eos-session-management-commands) ·
[EOS Configuration Sessions Overview](https://www.arista.com/en/um-eos/eos-configuration-sessions-overview) ·
[saidvandeklundert.net – configure sessions (community)](https://saidvandeklundert.net/2019-10-15-arista_configure_sessions/)

## 2. Generated commands

| Plan feature | Commands the driver sends | Evidence |
|---|---|---|
| Hostname / domain | `hostname <h>` · `dns domain <d>` | U **[LAB]** |
| Local admin | `username <u> privilege 15 role network-admin secret <pw>` | V (`username … secret`), U (`privilege 15 role network-admin`) **[LAB]** |
| SSH idle timeout | `management ssh` → `idle-timeout <min>` | V |
| VLAN | `vlan <id>` → `name <name>` | U **[LAB]** |
| Access port | `interface EthernetN` → `[description]` → `switchport mode access` → `switchport access vlan <id>` → `[spanning-tree portfast]` → `no shutdown` | U **[LAB]** |
| Trunk | `switchport mode trunk` → `switchport trunk native vlan <id>` → `switchport trunk allowed vlan <list>` | U **[LAB]** |
| SVI | `ip routing` (once) · `interface Vlan<id>` → `ip address A/L` → `no shutdown` | U **[LAB]** |
| Routed port | `interface EthernetN` → `no switchport` → `ip address A/L` | U **[LAB]** |
| DHCP server | `dhcp server` → `subnet P/L` → `name`, `range LO HI`, `default-gateway`, `dns server`, `lease time ipv4 D days H hours M minutes`; then `interface Vlan<id>` → `dhcp server ipv4` | V (pool), U (interface enable) **[LAB]** |
| NAT overload | ACL `NCS_NAT_INSIDE` + `ip nat source dynamic access-list NCS_NAT_INSIDE overload` on the outside interface | V syntax; support **depends on hardware** **[LAB]** |
| Static / default route | `ip route P/L <next-hop>` | U **[LAB]** |
| OSPF | `router ospf 1` → `router-id` → `network A/32 area N` → `passive-interface <if>` | U **[LAB]** |
| BGP | `router bgp <asn>` → `router-id` → `neighbor X remote-as N` → `network P/L` | U **[LAB]** |

The DHCP range is the largest free run inside the pool (EOS takes one range per subnet, not Cisco's
excluded addresses). EOS **silently disables** a subnet whose range is outside it or that overlaps another
subnet, so the backend validation rejects both cases before preview.

## 3. Refused with a clear error (never skipped)

| Plan option | Reason shown |
|---|---|
| EIGRP | "EIGRP is not supported on Arista EOS" (no EIGRP in the EOS manual) |
| Port security | not built for EOS yet (protect mode differs per platform) |
| Login banner | EOS types banners in a multi-line editor ending with `EOF`; not driven yet |
| `login block-for` | no EOS equivalent |
| Regenerate SSH keys | EOS manages its host keys itself |
| DHCP: different domains per pool, > 2 DNS servers | EOS takes one domain per server and two DNS servers per subnet |

## 4. Verification, errors and safety

- Verify: `show running-config` (each section kept), `show vlan`, `show interfaces <trunk> switchport`,
  `show ip interface brief`, `show ip ospf neighbor`, `show ip bgp summary` – all U **[LAB: freeze real output
  as golden fixtures]**.
- Management interface: the row in `show ip interface brief` that holds the management IP.
- Error patterns: `% Invalid input`, `% Incomplete command`, `% Ambiguous command`, `% Unrecognized command`,
  `% Unavailable command`, `% Error`, `% Maximum number` (C – from a third-party driver template **[LAB]**).
  Lines starting with `! ` are warnings, not errors.
- Extra denylist (custom commands): `configure session`, `commit`, `abort`, `rollback` – only the engine opens,
  commits or aborts a session.
- Discovery (Phase 4B): `show version`, `show hostname`, `show lldp neighbors detail` (U **[LAB]**).
- Netmiko `arista_eos` (4.8.0) has no commit helper: the engine sends the session commands itself and gives
  each one an expect string ([research/netmiko.md](research/netmiko.md) Q3, Q5).
