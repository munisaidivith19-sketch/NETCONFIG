# Arista EOS CLI syntax reference (cEOS-lab, 720XP/7xx campus, EOS 4.2x+)

Research date: 2026-11-11. Official pages consulted were EOS 4.35–4.37 user manual pages on arista.com.

**Method note (read first):** Many `arista.com/en/um-eos/...` pages returned HTTP 403 to the fetch tool (for example `eos-configure-session`, `eos-dhcp-server`, `eos-configuring-dhcp`, `eos-port-security`, and the 4.23.1F DHCP TOI, which redirects to a login page). Bypassing the bot check was refused and was not attempted again. The items below marked **[VERIFIED]** come from official Arista pages that did load (`eos-session-management-commands`, `eos-dhcp-overview`, `eos-data-plane-security`, `eos-user-security`, the TOI tag index) or from search snippets of official pages. Everything else is listed under **Gaps** as "likely syntax, UNVERIFIED this session". The generator must treat those as experimental until they are proven on cEOS-lab (CLAUDE.md §10: never invent device commands).

The fetched manual pages are machine-summarised extracts of very long pages, and several of them contain Arista's own typos (noted inline).

---

## 1. Safe change window: configuration sessions + commit timer

### Takeaway
Use `configure session <name>` from privileged EXEC. Stage the commands, then in session mode run `commit timer hh:mm:ss`. Confirm from EXEC with `configure session <name> commit` before the timer expires, otherwise EOS rolls back automatically. To discard a session, use `configure session <name> abort` (EXEC) or `abort` (inside session mode). Uncommitted sessions are lost on reboot and time out after 24 h.

### Cited Findings
- **`configure session [session_name] [abort | commit | [description description]]`**. Mode: **Privileged EXEC**. `no configure session <name>` / `default configure session` deletes the session. `abort` ends and deletes the session. `commit` commits the session's changes. If no name is given, EOS generates one (prompt example `switch(config-s-sess-1)#`). — [Arista EOS 4.37.0F Session Management Commands](https://www.arista.com/en/um-eos/eos-session-management-commands)
- Guidelines from the same page: "up to five uncommitted sessions"; **a reboot discards uncommitted sessions**; **uncommitted sessions time out after 24 hours**. — [Session Management Commands](https://www.arista.com/en/um-eos/eos-session-management-commands)
- On commit, the session config **replaces** the running-config, so changes made to running-config by others after the session started are overwritten. This matters for concurrent edits. — [Session Management Commands](https://www.arista.com/en/um-eos/eos-session-management-commands)
- **`commit timer hh:mm:ss`**. Mode: **Configure Session configuration mode** (prompt `switch(config-s-MySession)#`). Example: `commit timer 01:00:00`. If the changes are not confirmed within the interval, the switch rolls back automatically. — [Session Management Commands](https://www.arista.com/en/um-eos/eos-session-management-commands)
- **`service configuration session max completed <0-20> pending <1-20>`** (Global Config). Both defaults are 1 in the extract. When the pending limit is reached, new sessions are blocked until one is committed or aborted. (The "five uncommitted sessions" guideline above conflicts with "pending default 1", so check `show configuration sessions` on the target, which prints the max values in its header.) — [Session Management Commands](https://www.arista.com/en/um-eos/eos-session-management-commands)
- **`service configuration session commit timer default hh:mm:ss interactive`** (Global Config) sets a default timed commit. The command also has `merge` (three-way merge) and `save startup-config` options. — [Session Management Commands](https://www.arista.com/en/um-eos/eos-session-management-commands)
- **`show configuration sessions [detail]`** (EXEC). The header shows max completed/pending. Columns: Name, State, User, Terminal (some examples add Time). States: `pending`, `completed`, `aborted`. Terminal values: `vtyN` (SSH), `console`, `eAPI`. — [Session Management Commands](https://www.arista.com/en/um-eos/eos-session-management-commands)
- Worked flow (community, vEOS): `configure session acl-change` → `commit timer 00:05:00` → `show configuration sessions detail` shows state **`pendingCommitTimer`** with "Commit Time Left 4m56s" → `configure session acl-change commit` (from EXEC) → state `completed`. Rollback on expiry is logged as a config replace of `commitTimerCheckPointConfig`. `configure session <name> abort` removes a pending session. `show session-config diffs` (inside the session) shows a unified diff against running-config. — [saidvandeklundert.net (community)](https://saidvandeklundert.net/2019-10-15-arista_configure_sessions/); also [packetswitch.co.uk (community)](https://www.packetswitch.co.uk/how-to-use-arista-configure-session/)
- NAPALM's EOS driver uses this same mechanism for `commit_config(revert_in=N)` / `confirm_commit()` / `has_pending_commit()`. — [packetswitch.co.uk NAPALM + EOS (community)](https://www.packetswitch.co.uk/napalm-configuration-management-with-arista-eos/)

### Inferences
- Recommended driver flow (rollback_strategy = `"commit_timer"`, the EOS equivalent of Junos `commit confirmed`):
  1. EXEC: `configure session nc-<jobid>`
  2. Send the generated commands (they enter session config mode, prompt `(config-s-nc-<jobid>...)#`; note the prompt truncates the name, e.g. `config-s-acl-ch`).
  3. `show session-config diffs` (optional preview/audit)
  4. `commit timer 00:05:00` (applies now, auto-reverts at expiry)
  5. Run the verify show commands.
  6. On success, EXEC: `configure session nc-<jobid> commit`, then `write memory`. On failure: do nothing and let the timer expire, or use `configure replace` from the checkpoint (see Gaps). Before step 4, a failure is handled by `abort`.
- Session names: keep them short and alphanumeric with `-`/`_` (e.g. `nc-<8 hex>`). No official character or length rule was found.
- Because a commit replaces running-config wholesale, run sessions serially per device.

### Gaps
- Exact behaviour on SSH disconnect during a *pending* (uncommitted) session was not found. Per the guidelines it survives until it is committed or aborted, the 24 h timeout passes, or the device reboots. Behaviour of a `pendingCommitTimer` session on disconnect (it should still auto-revert when the timer expires) was not confirmed in docs; test on cEOS.
- No official command was found to *roll back early* while in `pendingCommitTimer`. Options to test: `configure session <name> abort`, or `configure replace checkpoint:...`. UNVERIFIED.
- Session-name allowed characters/length: not documented in the fetched text.

---

## 2. Hostname and DNS domain

### Takeaway
Not verified from official pages this session (the pages returned 403).

### Cited Findings
- (none verified)

### Gaps
- Likely syntax, UNVERIFIED this session: `hostname <NAME>` (Global Config). Domain: `dns domain <name>` (Global Config). EOS also historically accepts `ip domain-name <name>`, but treat that as an alias that `show running-config` may display differently. Confirm on cEOS before marking tested.

---

## 3. VLANs, access ports, trunks, port security

### Takeaway
Basic VLAN/switchport syntax is the industry-standard form, but it was not verified against an official page this session. EOS port-security syntax was not found in any official source the tool could load.

### Cited Findings
- An Arista support-tips index mentions a "protect mode for port security" (newer), which implies EOS supports at least shutdown and protect violation modes. No syntax was visible. — [Arista TOI index (search snippet)](https://www.arista.com/ko/support/toi/tag/toi?start=700)

### Gaps
- Likely syntax, UNVERIFIED this session:
  - `vlan <N>` → `name <NAME>` (VLAN config mode `config-vlan-N`)
  - Interface mode `interface Ethernet<N>`: `switchport mode access`, `switchport access vlan <N>`, `spanning-tree portfast`
  - `switchport mode trunk`, `switchport trunk native vlan <N>`, `switchport trunk allowed vlan <list>` (the list modifiers `add`/`remove` are likely)
  - `switchport port-security`, `switchport port-security mac-address maximum <N>`, `switchport port-security violation protect` (default violation = shutdown/errdisable). The protect mode is platform- and version-dependent (720XP support unknown).
  - EOS interface names: `Ethernet1`, `Ethernet1/1` on modular or breakout ports, `Port-Channel1`, `Vlan10`, `Management1` (cEOS: `Management0`). Validate against the catalog `port_prefix`.
- Official port-security page `https://www.arista.com/en/um-eos/eos-port-security` returned 403. Retrieve it manually.

---

## 4. SVI, ip routing, routed interface, static routes, default gateway

### Takeaway
Not verified from official pages this session.

### Gaps
- Likely syntax, UNVERIFIED this session: `interface Vlan<N>` → `ip address A.B.C.D/LEN`. EOS displays prefix notation, and dotted-mask input is believed to be accepted but is shown as /LEN. Global `ip routing` is needed for SVIs and routed ports to route; it is **disabled by default on EOS switches**, which is a key difference from Cisco L3 switches. Routed port: `interface Ethernet<N>` → `no switchport` → `ip address A.B.C.D/LEN`.
- Static route: `ip route A.B.C.D/LEN <next-hop> [<distance>]`. L2-only default gateway: `ip route 0.0.0.0/0 <GW>`. On some EOS versions the management interface may be in VRF `MGMT` (`ip route vrf MGMT 0.0.0.0/0 GW`), which is important for cEOS/real devices that use Management1 in a VRF.

---

## 5. DHCP server

### Takeaway
EOS has a native Kea-based DHCP server (**DHCPv4 since EOS 4.22.1**, DHCPv6 since 4.23.0). It is configured in global `dhcp server` mode with `subnet A.B.C.D/LEN` sub-mode (`range`, `default-gateway`, `dns server`, `lease time ipv4 ...`) and must also be enabled on the serving L3 interface. The interface command form for IPv4 was not visible in the extracts.

### Cited Findings
- "Support for DHCPv4 (RFC 2131) and DHCPv6 Server (RFC 8415) was added to EOS-4.22.1 and EOS-4.23.0 respectively". "EOS DHCP server leverages ISC Kea as backend". — [Arista TOI tag: dhcp-server](https://www.arista.com/en/support/toi/tag/dhcp-server)
- Global mode: `switch(config)# dhcp server` → `switch(config-dhcp-server)#`. Mode: Global Configuration. — [EOS DHCP overview / commands](https://www.arista.com/en/um-eos/eos-dhcp-overview)
- Inside `dhcp server`: `disabled`; `dns server ipv4 <addr> [<addr>]` ("Only two servers can be configured globally per address family"); `dns domain name ipv4 <name>`; `lease time ipv4 <D> days <H> hours <M> minutes` (days 0–2000, hours 0–23, minutes 0–59; example `lease time ipv4 1 days 0 hours 0 minutes`); `tftp server option 66|150 ipv4 ...`. — [EOS DHCP overview](https://www.arista.com/en/um-eos/eos-dhcp-overview)
- Subnet mode: `subnet 172.16.23.0/24` → prompt `config-dhcp-subnet-ipv4` (the manual's own examples use invalid `/32` prefixes, which is an Arista doc typo). Commands: `name <text>`, `range <start> <end>` ("The range must be within the subnet mask, otherwise the subnet becomes disabled"), `default-gateway <ipv4>`, `dns server <addr> [<addr>]` (max 2 per subnet), `lease time ipv4 ...`, `reservations` → `mac-address <mac>` → `ipv4-address <addr>`. "EOS disables overlapping subnets." — [EOS DHCP overview](https://www.arista.com/en/um-eos/eos-dhcp-overview); [EOS 4.37 IPv4 (search snippet)](https://www.arista.com/en/um-eos/eos-ipv4)
- The server can be enabled on routed ports, VLAN interfaces (SVIs), LAGs and sub-interfaces. Per-subnet settings override global settings. — [EOS 4.37 IPv4 (search snippet)](https://www.arista.com/en/um-eos/eos-ipv4)
- Show: `show dhcp server [ipv4|ipv6|leases|vrf]` (EXEC). Output starts with `IPv4 DHCP Server is active` / `DNS server(s): ...`, plus per-interface status, subnets, and the reason a subnet is disabled. `show dhcp server leases` lists IP, End, Last transaction, MAC address. — [EOS DHCP overview](https://www.arista.com/en/um-eos/eos-dhcp-overview)
- Community example (older): `subnet 10.0.0.0/24` / `range 10.0.0.2 10.0.0.10` / `name AP-Test` / `dns server 8.8.8.8` / `default-gateway 10.0.0.1`. — [Arista Community (community)](https://arista.my.site.com/AristaCommunity/s/question/0D5Uw00000DvNdIKAV/i-want-to-configiue-dhcp-on-arista-7050sx3-model-switch-anyone-can-guide-me-)

### Inferences
- Generator template (verify on cEOS):
  ```
  dhcp server
     subnet 10.10.10.0/24
        range 10.10.10.100 10.10.10.200
        default-gateway 10.10.10.1
        dns server 8.8.8.8
        lease time ipv4 1 days 0 hours 0 minutes
  interface Vlan10
     dhcp server ipv4
  ```
- If a range lies outside the subnet or subnets overlap, EOS *silently disables* the subnet instead of returning a CLI error. The backend validation must catch this, and verification must check `show dhcp server` for "disabled" reasons.

### Gaps
- Interface enable command: the extracts showed `dhcp server ipv6` under an interface. `dhcp server ipv4` is the logical IPv4 counterpart but was NOT seen verbatim. UNVERIFIED.
- One manual example uses the hyphenated `dhcp-server` (HA section) while the rest of the manual uses `dhcp server`. This is an inconsistency in the manual.
- Whether the DHCP server runs on cEOS-lab and on 720XP was not confirmed.

---

## 6. NAT

### Takeaway
EOS NAT is configured on the L3 **interface** (Ethernet, Port-Channel or VLAN interface mode). There is no inside/outside marking. Use `ip nat source dynamic access-list <ACL> overload` or `... pool <POOL>`, with a global `ip nat pool`. Support is **hardware-dependent**, and Arista sources conflict on whether overload/NAPT is supported on some platforms. Mark NAT experimental on EOS.

### Cited Findings
- `ip nat source dynamic access-list <acl_name> {overload | pool <pool_name>}`. Mode: Interface-Ethernet, Port-channel, VLAN config. Example: `ip nat source dynamic access-list accessList1 overload`. — [EOS Data Plane Security](https://www.arista.com/en/um-eos/eos-data-plane-security)
- `ip nat pool <name> <start> <end> {netmask <mask> | prefix-length <0-32>}` (Global Config). Example: `ip nat pool p1 10.15.15.15 10.15.15.25 prefix-length 24`. — [EOS Data Plane Security](https://www.arista.com/en/um-eos/eos-data-plane-security)
- Static: `ip nat source static <original> <translated> ...` (interface mode). Example: `ip nat source static 10.24.1.10 168.32.14.15`. — [EOS Data Plane Security](https://www.arista.com/en/um-eos/eos-data-plane-security)
- "The switch uses a common NAT table for the entire switch, not a per interface." NAT should be configured on an L3 interface (routed port or SVI). — [EOS Data Plane Security (search snippet)](https://www.arista.com/en/um-eos/eos-data-plane-security)
- Show: `show ip nat translation [... dynamic | hardware | static | summary ...]` (EXEC). `ip nat translation counters` is DCS-7150 only. Dynamic NAT with an ACL destination port is not supported on 7050SX3. — [EOS Data Plane Security](https://www.arista.com/en/um-eos/eos-data-plane-security)
- Conflict: an Arista dynamic-NAT TOI (tagged DCS-7050CX4) states "NAPT is not supported in masquerade or overload mode." — [Arista TOI tag dcs-7050cx4 (search snippet)](https://www.arista.com/ko/support/toi/tag/dcs-7050cx4)
- Static NAT on 7050X3/720XP/720D was first introduced in 4.21.6F. A TOI covers "Dynamic NAT profile" options on 7050X3 and 720XP. — [Arista TOI tag ccs-720xp (search snippet)](https://www.arista.com/en/support/toi/tag/ccs-720xp)
- Security advisory 0078: a security ACL bypass when dynamic NAT is on one interface and an ACL is on another; it affects 720XP among others (4.24.9 and below in the 4.24 train). — [Arista Security Advisory 0078](https://www.arista.com/zh/support/advisories-notices/security-advisory/15862-security-advisory-0078)

### Inferences
- The EOS driver should map the plan's NAT-overload to: an ACL (`ip access-list <NAME>` / `10 permit ip <inside>/LEN any`), and on the *outside* interface `ip nat source dynamic access-list <NAME> overload`. Gate it with a capability flag per model, default off for 720XP and the 7050 family, and label it experimental.
- cEOS-lab forwards in software. Whether NAT works in cEOS is unknown, so test it.

### Gaps
- Overload support per platform (720XP, cEOS) is unresolved because the official sources conflict.

---

## 7. OSPF, BGP, EIGRP

### Takeaway
Not verified from official pages this session.

### Gaps
- Likely syntax, UNVERIFIED this session: `router ospf <id>` → `router-id A.B.C.D`, `network A.B.C.D/LEN area <N>` (EOS uses prefix notation, not wildcard masks), `passive-interface <IF>` (or `passive-interface default`). Interface-level alternative: `ip ospf area <N>`. Show: `show ip ospf neighbor`.
- BGP: `router bgp <ASN>` → `router-id A.B.C.D`, `neighbor <IP> remote-as <N>`, `neighbor <IP> description <text>`, `network A.B.C.D/LEN`. Neighbors are believed to be activated for IPv4 unicast by default unless `no bgp default ipv4-unicast` is set. Show: `show ip bgp summary`. Note that ipspace.net reports EOS treats only "Invalid input" as an error inside config sessions for some BGP commands — [ipspace.net 2025 (community)](https://blog.ipspace.net/2025/09/eos-no-interfaces/).
- EIGRP: believed **not supported on EOS** (no EIGRP chapter exists in the EOS manual index). Raise "not supported on Arista EOS". Not confirmed against an official statement this session.

---

## 8. Local users, SSH, enable, hardening, banner

### Takeaway
`username` and `enable password` are verified. The SSH idle timeout (`management ssh` → `idle-timeout <min>`, default 0 = disabled) and banners terminated by a line containing only `EOF` are verified from official snippets. `privilege 15 role network-admin` is documented as a role keyword, but the `privilege` keyword was not visible in the extract.

### Cited Findings
- `username <name> secret [0|5|sha512] <pw>`, `username <name> nopassword`, `username <name> role <role>`. A role can be set on creation: `username FRED secret 0 axced role sysuser1`. `no username <name>`. Mode: Global Config. — [EOS User Security](https://www.arista.com/en/um-eos/eos-user-security)
- `enable password [0|5] <pw>`, `no enable password`. With no enable password set, `enable` does not prompt. Passwords are stored hashed in running-config (the manual says SHA-512 but shows MD5 `$1$` examples, an inconsistency in the manual). `enable secret` was not covered in the extract. — [EOS User Security](https://www.arista.com/en/um-eos/eos-user-security)
- `management ssh` → `idle-timeout <minutes>`. "Automatic connection timeout is disabled by setting the idle-timeout to zero, which is the default setting." Example `idle-timeout 180`. — [EOS Connection Management (search snippet)](https://arista.com/um-eos/eos-connection-management)
- DISA STIG for Arista EOS 4.2x expects `management ssh` / `idle-timeout 10`. — [STIG Viewer V-255956](https://STIGVIEWER.com/stig/arista_mls_eos_4.2x_ndm/2023-01-11/finding/V-255956)
- EOS 4.36.0F adds an absolute user session timeout for console/SSH/telnet. — [Arista connection management (search snippet)](https://www.arista.com/en/um-eos/eos-connection-management)
- Banners: `banner motd` / `banner login` open an editor, and "To end the banner editing session, type EOF on its own line and press enter." motd is shown on console, telnet and ssh. — [EOS Switch Administration Commands (search snippet)](https://www.arista.com/en/um-eos/eos-switch-administration-commands)

### Inferences
- Generator: `username <u> privilege 15 role network-admin secret <pw>` (mask the line). For the banner, emit `banner motd`, the text lines, then `EOF`. Validation must reject any banner line equal to `EOF` (case-insensitive) to prevent early termination or injection.
- Netmiko `send_config_set` should handle the multi-line banner (each line is sent and the EOF line closes it), but test it, because prompt detection changes inside the banner editor.

### Gaps
- `privilege 15` keyword and the `network-admin` role name: likely correct (`network-admin` and `network-operator` are the default EOS roles), but not seen verbatim. UNVERIFIED.
- SSH enabled by default: believed yes on EOS (`management ssh` without `shutdown`). Not confirmed.
- `management api http-commands`: believed disabled by default (`shutdown`). Hardening = keep it `shutdown`, or use `no protocol http` and only `protocol https`. UNVERIFIED.
- No EOS equivalent of `service password-encryption` was found. EOS stores secrets hashed by default per the User Security page.

---

## 9. Save

### Gaps
- Likely syntax, UNVERIFIED this session: `write memory` or `copy running-config startup-config` (EXEC). `service configuration session commit save startup-config` (verified, see §1) can auto-save on session commit — [Session Management Commands](https://www.arista.com/en/um-eos/eos-session-management-commands). Do not enable that option, because it would save before verification.

---

## 10. CLI error strings

### Takeaway
No official Arista list was found. A third-party driver's patterns and community reports give the set to match.

### Cited Findings
- Third-party Arista template error patterns: `% Invalid input`, `% Ambiguous command`, `% Unrecognized command`, `% Incomplete command`. — [rneter crate arista.rs (community)](https://docs.rs/crate/rneter/0.4.1/source/src/templates/network/arista.rs)
- EOS rejects some commands in a config session with `% Invalid input`. — [ipspace.net (community)](https://blog.ipspace.net/2025/09/eos-no-interfaces/)

### Inferences
- Error patterns for the driver: `% Invalid input`, `% Incomplete command`, `% Ambiguous command`, `% Unrecognized command`, `% Unavailable command` (EOS prints this for features the hardware does not support; UNVERIFIED wording), and the generic `% Error`. Matching on a leading `% ` followed by the error text is reasonable, but avoid false positives in show output.

---

## 11. Verification show commands and output formats

### Cited Findings
- `show configuration sessions [detail]` — see §1. `show dhcp server [ipv4]`, `show dhcp server leases` — see §5. `show ip nat translation` — see §6.

### Gaps (likely, UNVERIFIED; capture real output from cEOS for golden files)
- `show vlan` (EOS has no `show vlan brief`): columns VLAN, Name, Status, Ports.
- `show interfaces status`: Port, Name, Status, Vlan, Duplex, Speed, Type, Flags.
- `show interfaces Ethernet1 switchport`: Operational Mode, Access Mode VLAN, Trunking Native Mode VLAN, Trunking VLANs Enabled.
- `show ip interface brief`: columns Interface, IP Address, Status, Protocol, MTU, plus Owner on newer releases. The layout changed across 4.2x releases, so parse tolerantly.
- `show lldp neighbors detail`: Chassis ID, Port ID, System Name, Management Address.
- `show version`: model line (e.g. `Arista DCS-7050...` / `cEOSLab`), `Serial number:`, `Software image version:`, `System MAC address:`.
- `show ip ospf neighbor`, `show ip bgp summary`, `show running-config [section X]`.
- **Recommendation:** append `| json` to show commands (EOS supports JSON output for most show commands). This avoids text parsing and makes `check()` and `management_interface()` robust. UNVERIFIED this session, but widely used through eAPI.
