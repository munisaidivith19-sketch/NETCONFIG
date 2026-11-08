# Cisco IOS / IOS-XE driver reference (`cisco_ios`)

Status: **experimental** – researched from Cisco documentation (2026-11-08). The driver stays
experimental until every item marked **[LAB]** has been checked on IOSv / IOSvL2 (`docs/LAB_TESTING.md`).
Command syntax differs between platforms and releases. Where Cisco documents a difference, it is
written here and the driver handles it with a model flag.

Conventions: `<x>` = value from the plan; `[x]` = optional. Everything is entered in global
configuration mode unless shown otherwise.

---

## 1. Safe change window (rollback)

| Step | Command | Notes |
|---|---|---|
| Prerequisite – configuration archive | `archive` → `path <fs>:ncs-archive` → `maximum 5` | The archive must exist before a timed rollback can be used. `<fs>` is `flash:` on Catalyst; IOSv uses `flash0:` **[LAB]**. The driver picks it from `show file systems`. |
| Enter config mode with an automatic rollback | `configure terminal revert timer <1-120>` | Minutes. The `revert` keyword was added in 12.4(20)T. If the change is not confirmed in time, the device restores the previous configuration by itself. |
| Keep the change | `configure confirm` (privileged EXEC) | Sent only after verification passes. |
| Roll back now | `configure revert now` (privileged EXEC) | Used on a CLI error or a failed verification. |
| Extend the timer | `configure revert timer <minutes>` | Not used by default. |

Rule (validation): the revert timer must be longer than the time needed for apply + verification
(default 10 minutes; OSPF/BGP checks wait for convergence inside this window).

Sources:
[Configuration Fundamentals Command Reference – `configure terminal` (revert option)](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/fundamentals/command/cf_command_ref/C_commands.html) ·
[Configuration Rollback Confirmed Change, IOS XE 17](https://www.cisco.com/c/en/us/td/docs/routers/ios/config/17-x/syst-mgmt/b-system-management/m_cm-config-rollback-confirmed-change.html) ·
[Configuration Rollback Confirmed Change, IOS XE 16.6](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/config-mgmt/configuration/xe-16-6/config-mgmt-xe-16-6-book/cm-config-rollback-confirmed-change.html) ·
[Configuration Replace and Configuration Rollback (Catalyst 9400, IOS XE 26.x)](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9400/software/release/26-x/configuration_guide/sys_mgmt/b_26x_sys_mgmt_9400_cg/configuration_replace_and_configuration_rollback.html)

Verify: `show archive` lists the archive files; `show archive config rollback timer` shows a
pending timer **[LAB]**.

---

## 2. Basic settings

```
hostname <hostname>
ip domain name <domain>
```
- Hostname: letters, digits, hyphens; validated by the plan (no spaces, `;`, `|`, `#`).
- `ip domain name` is the current form. Older releases also accept `ip domain-name` **[LAB: confirm which form IOSv 15.x accepts]**.

Verify: `show running-config | include ^hostname|^ip domain`

---

## 3. VLANs

```
vlan <id>
 name <name>
```
- Valid IDs 1–4094; 1002–1005 are reserved. NetConfig Studio allows 2–4094 except 1002–1005.
- Name: `[A-Za-z0-9_-]{1,32}`.

Verify: `show vlan brief` – one row per VLAN: `<id> <name> active <ports>`.

Source: [VLAN Configuration Guide, IOS XE 17.14 (Catalyst 9400) – Configuring VLAN Trunks](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9400/software/release/17-14/configuration_guide/vlan/b_1714_vlan_9400_cg/configuring_vlan_trunks.html)

---

## 4. Access ports

```
interface range <if-list>          ! or a single "interface <if>"
 description <text>
 switchport mode access
 switchport access vlan <vlan>
 spanning-tree portfast            ! see platform note
 no shutdown
```
- `switchport mode access` makes the port permanently non-trunking; the default mode is dynamic auto.
- **PortFast platform note:** recent Catalyst/IOS-XE releases use `spanning-tree portfast` (saved as
  `spanning-tree portfast edge` from 15.2(4)E); some Catalyst 9500 models require
  `spanning-tree portfast edge`. The driver uses `spanning-tree portfast` unless the model sets
  `portfast_keyword: "edge"` **[LAB]**.
- PortFast only on ports that connect to end hosts – never on links to other switches.
- `interface range` takes comma-separated items, for example
  `interface range GigabitEthernet1/0/1 - 12 , GigabitEthernet1/0/20` **[LAB: spacing accepted by IOSvL2]**.
  Until that spacing is confirmed in the lab, the driver emits one `interface <if>` block per port
  (longer, but every line is a documented command). `interface range` is a later optimisation.

### Port security (optional per access port group)
```
 switchport port-security
 switchport port-security maximum <1-n>
 switchport port-security violation {protect | restrict | shutdown}
 [switchport port-security mac-address sticky]
```
- Requires the port to be in access mode first (the driver always emits `switchport mode access` before it).
- Defaults: maximum 1, violation `shutdown` (port goes err-disabled).
- Voice VLAN ports need maximum ≥ 2. The maximum cannot be set below the number of addresses already secured (command rejected).

Verify: `show interfaces status`, `show interfaces <if> switchport`, `show port-security interface <if>`

Sources:
[VLAN Trunks (switchport modes)](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9400/software/release/17-14/configuration_guide/vlan/b_1714_vlan_9400_cg/configuring_vlan_trunks.html) ·
[Optional Spanning-Tree Features, IOS XE 17.17 (Catalyst 9500)](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9500/software/release/17-17/configuration_guide/lyr2/b_1717_lyr2_9500_cg/configuring_optional_spanning_tree_features.html) ·
[Optional Spanning-Tree Features, 15.2(2)E (Catalyst 2960-XR)](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst2960xr/software/15-2_2_e/consolidated_guide/b_1522e_consolidated_2960xr_cg/b_1522e_consolidated_2960xr_cg_chapter_010001.html) ·
[Port Security, IOS XE 17.12 (Catalyst 9300)](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-12/configuration_guide/sec/b_1712_sec_9300_cg/port_security.html) ·
[Port Security, 15.2(7)E (Catalyst 2960-L)](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst2960l/software/15-2_7_e/configuration_guide/sec/b_1527e_security_2960l_cg/port_security.html)

---

## 5. Trunks

```
interface <if>
 description <text>
 switchport trunk encapsulation dot1q     ! ONLY on platforms that also support ISL (model flag)
 switchport mode trunk
 switchport trunk native vlan <vlan>
 switchport trunk allowed vlan <list>
 no shutdown
```
- `switchport trunk encapsulation dot1q` is required before `switchport mode trunk` on switches that
  support both ISL and 802.1Q (for example IOSvL2, Catalyst 3560/3750). On 802.1Q-only platforms
  (Catalyst 2960, 9000) the command does not exist and returns `% Invalid input`. The driver emits it
  only when the model sets `trunk_encapsulation_cmd: true`.
- The native VLAN defaults to VLAN 1. All VLANs are allowed by default. NetConfig Studio always writes
  an explicit allowed list.
- The list format is `10,20,30-35`. The driver never uses `add`/`remove`, so the final state is exact.

Verify: `show interfaces trunk` – sections "Port Mode Encapsulation Status Native vlan" and
"Vlans allowed on trunk".

Source: [Configuring VLAN Trunks, IOS XE 17.14 (Catalyst 9400)](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9400/software/release/17-14/configuration_guide/vlan/b_1714_vlan_9400_cg/configuring_vlan_trunks.html) ·
[Configuring VLAN Trunks, IOS XE 16.9 (Catalyst 3850)](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst3850/software/release/16-9/configuration_guide/vlan/b_169_vlan_3850_cg/configuring_vlan_trunks.html)

---

## 6. SVIs and IP routing (Layer 3 switches)

```
ip routing
interface Vlan<id>
 description <text>
 ip address <ip> <mask>
 no shutdown
```
- IP routing is disabled by default on switches and must be enabled. Routers route by default.
- One SVI per VLAN. An SVI comes up only when the VLAN is active on at least one up port.
- Licence/image limits: with Network Essentials only static routing and RIP are available on some
  Catalyst 9200 models. Older 2960 switches need `sdm prefer lanbase-routing` and a reload, which
  NetConfig Studio never does automatically.

Verify: `show ip interface brief` – `Vlan10  10.0.10.1  YES manual up  up`; `show ip route connected`.

Sources: [Configuring IP Unicast Routing, IOS XE 26.x (Catalyst 9300)](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/26-x/configuration_guide/rtng/b_26x_rtng_9300_cg/configuring_ip_unicast_routing.html) ·
[Configure Inter-VLAN Routing with Catalyst Switches](https://www.cisco.com/c/en/us/support/docs/lan-switching/inter-vlan-routing/41260-189.html) ·
[Interface Characteristics, IOS XE 16.10 (Catalyst 9200)](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9200/software/release/16-10/configuration_guide/int_hw/b_1610_int_and_hw_9200_cg/configuring_interface_characteristics.html)

---

## 7. Routed interfaces

```
interface <if>
 description <text>
 no switchport               ! only on Layer 3 switches (model category l3switch)
 ip address <ip> <mask>
 no shutdown
```
Verify: `show ip interface brief`.

---

## 8. DHCP server

```
ip dhcp excluded-address <low> [<high>]
ip dhcp pool <NAME>
 network <network> <mask>
 default-router <gateway>
 dns-server <dns1> [<dns2> …]          ! up to 8, in order of preference
 [domain-name <domain>]
 [lease <days> [<hours>]]
```
- Exclude the gateway and any static addresses first. The router's own interface address is excluded automatically.
- The default router must be on the client subnet (NetConfig Studio validates that it is inside the pool network).

Verify: `show ip dhcp pool`, `show ip dhcp binding`.

Sources: [Configuring the Cisco IOS XE DHCP Server, IOS XE 17](https://www.cisco.com/c/en/us/td/docs/routers/ios/config/17-x/ip-addressing/b-ip-addressing/m_config-dhcp-server-xe.html) ·
[Configuring the Cisco IOS DHCP Server, 12.4](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/ipaddr_dhcp/configuration/12-4/dhcp-12-4-book/config-dhcp-server.html)

---

## 9. NAT overload (PAT)

```
ip access-list standard NCS_NAT_INSIDE
 permit <network> <wildcard>
interface <inside-if>
 ip nat inside
interface <outside-if>
 ip nat outside
ip nat inside source list NCS_NAT_INSIDE interface <outside-if> overload
```
- The overload interface must be a Layer 3 interface with a valid IP address that is up.
- NAT is offered only for routers in the catalog (L3 switches often lack NAT in their licence).

Verify: `show ip nat statistics` (inside/outside interfaces listed), `show ip nat translations`.

Sources: [Configuring NAT for IP Address Conservation, IOS XE 17](https://www.cisco.com/c/en/us/td/docs/routers/ios/config/17-x/ip-addressing/b-ip-addressing/m_iadnat-addr-consv-xe.html) ·
[Configuring NAT, IOS XE 17.6 (Catalyst 9600)](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9600/software/release/17-6/configuration_guide/ip/b_176_ip_9600_cg/configuring_network_address_translation.html)

---

## 10. Static routes

```
ip route <prefix> <mask> {<next-hop-ip> | <exit-interface>} [<distance>]
```
- Default route: `ip route 0.0.0.0 0.0.0.0 <next-hop>`.

Verify: `show ip route static`.

Sources: [Configuring IP Unicast Routing, IOS XE 26.x](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/26-x/configuration_guide/rtng/b_26x_rtng_9300_cg/configuring_ip_unicast_routing.html) ·
[Configuring Static IP Routing, 15.2(2)E (Catalyst 2960)](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst2960/software/release/15-2_2_e/configuration/guide/b_1522e_2960_2960c_2960s_2960sf_2960p_cg/b_1522e_2960_2960c_2960s_2960sf_2960p_cg_chapter_0100001.html)

---

## 11. OSPF (single area or multi-area)

```
router ospf <process-id>
 router-id <a.b.c.d>
 network <interface-ip> 0.0.0.0 area <area>     ! one per participating interface (exact match)
 passive-interface <if>                          ! LAN/SVI interfaces with no OSPF neighbours
```
- NetConfig Studio uses exact `0.0.0.0` wildcards so only the chosen interfaces join OSPF.

Verify: `show ip ospf neighbor` – state `FULL/…` per neighbour; `show ip ospf interface brief`; `show ip route ospf`.

Source: [Configuring OSPF, IOS XE 16](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/iproute_ospf/configuration/xe-16/iro-xe-16-book/iro-cfg.html)

---

## 12. EIGRP (classic mode)

```
router eigrp <as 1-65535>
 eigrp router-id <a.b.c.d>
 network <network> <wildcard>
 passive-interface <if>
 no auto-summary
```
- Named mode (`router eigrp <name>` + `address-family ipv4 unicast autonomous-system <as>`) exists
  but is not generated in v1.

Verify: `show ip eigrp neighbors`, `show ip route eigrp`.

Sources: [IP Routing Configuration Guide – EIGRP (IOS XE)](https://www.cisco.com/c/en/us/td/docs/routers/ios-xe/ip-routing/b-ip-routing/m_ire-enhanced-igrp.html) ·
[Configuring EIGRP, IOS XE 17.4 (Catalyst 9300)](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-4/configuration_guide/rtng/b_174_rtng_9300_cg/configuring_eigrp.html)

---

## 13. BGP (eBGP neighbours)

```
router bgp <asn>
 bgp router-id <a.b.c.d>
 neighbor <ip> remote-as <asn>
 neighbor <ip> description <text>
 network <prefix> mask <mask>       ! announced only if the prefix is in the routing table
```
- AS numbers: 1–4294967295 (4-byte). 64512–65534 and 4200000000–4294967294 are private.
- eBGP neighbours are normally directly connected.

Verify: `show ip bgp summary` – neighbour row with a number (prefixes received) in the last column
means Established; `show ip bgp`.

Sources: [Configuring BGP, IOS XE 17.16 (Catalyst 9600)](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9600/software/release/17-16/configuration_guide/rtng/b_1716_rtng_9600_cg/configuring_bgp.html) ·
[Connecting to a Service Provider Using External BGP](https://www.cisco.com/c/en/us/td/docs/routers/ios-xe/ip-routing/b-ip-routing/m_irg-external-sp-0.html)

---

## 14. SSH v2 and management access

```
hostname <hostname>                       ! required before RSA keys
ip domain name <domain>                   ! required before RSA keys
username <user> privilege 15 secret <password>
enable secret <secret>
crypto key generate rsa modulus 2048      ! see prompt note
ip ssh version 2
line vty 0 4
 login local
 transport input ssh
 exec-timeout 10 0
```
- Cisco recommends 2048-bit or larger keys; 768 is the minimum for SSH v2.
- `transport input ssh` refuses Telnet on the VTY lines.
- **Prompt:** if keys already exist the device asks `Do you really want to replace them? [yes/no]:`.
  The push engine checks `show crypto key mypubkey rsa` first and does not regenerate existing keys
  unless the plan asks for it explicitly (Phase 3A handles the prompt).
- VTY ranges differ (routers `0 4`, Catalyst `0 15`). The driver writes `line vty 0 4`, plus
  `line vty 5 15` when the model sets `vty_lines: 16` **[LAB]**.
- **Management protection:** when connected over SSH, the plan must not remove `transport input ssh`,
  `login local` or the user it is logged in with.

Verify: `show ip ssh` (`SSH Enabled - version 2.0`), `show running-config | section line vty`.

Sources: [Configure SSH on Routers](https://www.cisco.com/c/en/us/support/docs/security-vpn/secure-shell-ssh/4145-ssh.html) ·
[Secure Shell Version 2, IOS XE 17](https://www.cisco.com/c/en/us/td/docs/switches/lan/c9000/sec-crypto/ssh/secure-shell-configuration-guide/m-secure-shell-version-2.html)

---

## 15. Hardening

```
service password-encryption
no ip http server
no ip http secure-server
login block-for <seconds> attempts <tries> within <seconds>
banner motd #<text>#
```
- `service password-encryption` is only *weak, reversible* obfuscation of type-7 passwords. Real
  protection comes from `secret` (hashed) and from never storing configs in clear text.
- `login block-for` applies to Telnet and SSH and must come before other login commands.
  Default plan: `login block-for 120 attempts 5 within 60`.
- **Banner delimiter:** the delimiter character must not appear in the text. NetConfig Studio uses `#`
  and validation forbids `#` (and `^C`, newlines, `|`, `;`) in banner text, so the text cannot close
  the banner early and inject commands.

Sources: [Harden IOS Devices](https://www.cisco.com/c/en/us/support/docs/ip/access-lists/13608-21.html) ·
[Configuring Security with Passwords, Privileges, and Logins, IOS XE 17](https://www.cisco.com/c/en/us/td/docs/routers/ios/config/17-x/sec-vpn/b-security-vpn/m_sec-cfg-sec-4cli-0.html) ·
[Configuring Login Block, IOS XE 17.17 (Catalyst 9600)](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9600/software/release/17-17/configuration_guide/sec/b_1717_sec_9600_cg/configuring_login_block.html) ·
[Managing Connections, Menus, and System Banners, 12.2SR](https://www.cisco.com/c/en/us/td/docs/ios/fundamentals/configuration/guide/12_2sr/cf_12_2sr_book/cf_connections.html)

---

## 16. Saving

`write memory` (equivalent to `copy running-config startup-config`). Sent only after `configure confirm`.

---

## 17. CLI error messages (stop on first match)

| Device output | Meaning |
|---|---|
| `% Invalid input detected at '^' marker.` | Wrong or unsupported command; `^` marks the position |
| `% Incomplete command.` | A required keyword or value is missing |
| `% Ambiguous command:` | Abbreviation matches several commands |
| `% Unknown command or computer name` | Command typed in the wrong mode |
| `% Bad mask` / `% Inconsistent address and mask` | Invalid IP address/mask pair |
| `overlaps with` | New subnet overlaps an existing interface subnet |
| `% Invalid VLAN` / `Command rejected` | VLAN or interface rejected the setting |

Informational lines that are **not** errors: `% Access VLAN does not exist. Creating vlan <n>`,
`%LINK-…`/`%LINEPROTO-…` syslog messages, `% Warning: …` (logged as a warning).

Source: [Using the Command-Line Interface, 15.2(2)E (Catalyst 2960-XR)](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst2960xr/software/15-2_2_e/int_hw_components/configuration_guide/b_int_1522e_2960xr_cg/b_int_152ex1_2960-xr_cg_chapter_01.html) ·
[Catalyst 9800 Command Reference – Using the CLI](https://www.cisco.com/c/en/us/td/docs/wireless/controller/9800/command-reference/b_wireless_cr/using-the-command-line-interface.html)

---

## 18. Model flags used by this driver (catalog)

| Flag | Default | Set on |
|---|---|---|
| `trunk_encapsulation_cmd` | `false` | IOSvL2 |
| `portfast_keyword` | `""` (plain `spanning-tree portfast`) | `"edge"` for models that require it |
| `vty_lines` | `5` | `16` on Catalyst 2960-X / 9300 |
| `archive_fs` | `flash:` | `flash0:` on IOSv / IOSvL2 **[LAB]** |

## 19. Implementation notes (Phase 2B)
- `app/drivers/cisco_ios.py` implements every section above; golden files are in `backend/tests/golden/cisco_ios/`.
- Interface abbreviations (`gi1/0/1`, `te1/1/1`, `vl10`, `po1`) are expanded before validation; an ambiguous
  abbreviation (`f0/1`, `t1/0/1`) is left as typed and fails the model's port pattern.
- `crypto key generate rsa` is listed in the preview; the push engine (Phase 3A) sends it only when
  `show crypto key mypubkey rsa` shows no key, or when the plan asks to replace the keys.
- Verification reads `show running-config` for settings without a dedicated show command (hostname,
  hardening, static routes, EIGRP networks, VTY lines). Neighbour/up-down state checks are informational
  and do not fail a push on their own.

## 20. Push notes (Phase 3A)
- Session: Netmiko `cisco_ios` (`cisco_ios_telnet` for lab consoles, `cisco_ios_serial` for a console cable),
  `session_log=None`, `fast_cli=False`. Config lines are sent one at a time so the first error pattern
  (section 17) stops the push at the exact command.
- The `archive` block (`path <fs>ncs-archive`, `maximum 5`) is added in a separate `configure terminal`
  session only when `show running-config` has no `archive` / `path`. The change itself is applied inside
  `configure terminal revert timer N` (N = plan `revert_minutes`, default 10). After verification:
  `configure confirm`, then `write memory`. On failure: `configure revert now`.
- `crypto key generate rsa modulus N` asks "Do you really want to replace them? [yes/no]" when keys exist.
  It is only sent when `show crypto key mypubkey rsa` shows no key or the plan sets `regenerate_keys`;
  the prompt is then answered `yes` (Netmiko `send_command` with `expect_string`).
- Still **experimental**: none of this has been run on IOSv / IOSvL2 yet. The checklist is in
  `docs/LAB_TESTING.md` (Phase 3B); only after it passes is the driver marked `tested`.
