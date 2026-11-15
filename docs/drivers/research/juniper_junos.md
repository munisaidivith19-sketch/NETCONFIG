# Juniper Junos CLI syntax (EX/ELS, vJunos-switch, SRX300) for NetConfig Studio

> Researched 2026-11-11. **Important source note:** every `www.juniper.net/documentation/...` URL now returns
> `301 Moved Permanently` to the same path on `networkingdocs.hpe.com` (HPE acquired Juniper). The URLs below
> are the canonical juniper.net paths; swap the host to `networkingdocs.hpe.com` if a link does not open.
> The HPE pages render their CLI code blocks with JavaScript, so automated fetching often returned the prose
> but **not** the command text. Where an exact command could not be read from an official page this session,
> it is listed under **Inferences** as "unverified – from general Junos knowledge" and must be proven in the
> vJunos lab (CLAUDE.md §10: never invent commands; mark untested as experimental).
>
> Legend: **[V]** = command text read verbatim from the cited page this session. **[P]** = behaviour/prose
> confirmed, exact text not shown. **[U]** = unverified, lab-test before use.

## 1. Safe change window (configure private / exclusive, commit check, commit confirmed, rollback)

### Takeaway
Use `configure private` (or `configure exclusive`) → `set ...` lines → `show | compare` → `commit check` →
`commit confirmed N` (1–65,535 min, default 10) → verify → `commit` (or `commit check`) to confirm. If not
confirmed in time Junos automatically rolls back to the pre-commit config. `rollback 0` (or plain `rollback`
in private mode) discards uncommitted candidate changes.

### Cited Findings
- [P] Three modes: `configure` — "All users can commit any changes"; `configure exclusive` — "Only the user who has locked the configuration can commit it"; `configure private` — each user gets a private candidate; with conflicting commits "the first commit operation takes precedence over subsequent commit operations." — [Overview of the Configure Command](https://www.juniper.net/documentation/us/en/software/junos/cli/topics/topic-map/configure-command.html)
- [P] Private mode works on a copy of the most recently committed shared config; if the global config changes, use the `update` command (merge conflicts possible). — [Configure Command](https://www.juniper.net/documentation/us/en/software/junos/cli/topics/topic-map/configure-command.html)
- [P] "You can also issue the rollback command to discard your private candidate configuration changes and obtain the most recently committed configuration." — [Configure Command](https://www.juniper.net/documentation/us/en/software/junos/cli/topics/topic-map/configure-command.html)
- [P] "When you use the yes option to exit configure exclusive mode, Junos OS discards any uncommitted changes and rolls backs the configuration to its previously committed state." The `no` option keeps you in config mode. — [Configure Command](https://www.juniper.net/documentation/us/en/software/junos/cli/topics/topic-map/configure-command.html)
- [P] "When one user exits configure exclusive mode while another user is in configure private mode, Junos OS rolls back any uncommitted changes in the private mode session." — [Configure Command](https://www.juniper.net/documentation/us/en/software/junos/cli/topics/topic-map/configure-command.html)
- [P] In exclusive mode, an unconfirmed `commit confirmed` causes an automatic rollback, the lock is removed and the error "access has been revoked" is shown. — [Configure Command](https://www.juniper.net/documentation/us/en/software/junos/cli/topics/topic-map/configure-command.html)
- [P] Junos does not support `configure private` for third-party YANG (OpenConfig/custom) statements; in a chassis cluster (SRX HA) plain `configure` puts you into private mode. — [Configure Command](https://www.juniper.net/documentation/us/en/software/junos/cli/topics/topic-map/configure-command.html)
- [V] `commit check`: "Verify the syntax of the configuration, but do not activate it." "You cannot include a comment with the commit check command." — [commit (CLI reference)](https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/command/commit.html)
- [V] `commit confirmed <minutes>`: "The allowed range is 1 through 65,535 minutes, and the default is 10 minutes." On timeout "the configuration rolls back automatically to the precommit configuration" (search snippet adds: "and a broadcast message is sent to all logged-in users"). — [commit](https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/command/commit.html)
- [V] "To confirm a commit, enter either a commit or commit check command." — [commit](https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/command/commit.html)
- [V] "In Junos OS Release 11.4 and later, you can also use the commit confirmed command in the [edit private] configuration mode." — [commit](https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/command/commit.html)
- [V] `commit comment "text"` — comment up to 512 bytes, single line. `commit and-quit` — commits and exits config mode if no errors. — [commit](https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/command/commit.html)
- **Conflict:** the Junos XML/NETCONF protocol docs say "The confirmed-commit operation is not available for a private copy." (applies to `<open-configuration><private/>` over NETCONF, not to the CLI that Netmiko drives). — [Commit a Private Copy (Junos XML protocol)](https://www.juniper.net/documentation/us/en/software/junos/junos-xml-protocol/topics/task/junos-xml-protocol-configuration-committing-private-copy.html) vs [commit](https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/command/commit.html)
- [P] `rollback 0` discards any pending, uncommitted changes from the candidate configuration; `rollback N` loads a previous committed config into the candidate (must then `commit`). — [rollback (CLI reference)](https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/command/rollback.html)
- (Community, not official) "If you are in 'private' mode, again your uncommitted changes are discarded if you log out." — [Juniper community: Discarding uncommitted changes](https://community.juniper.net/discussion/discarding-uncommitted-changes)

### Inferences
- Recommended push sequence for the Junos driver (rollback_strategy = `commit_confirmed`):
  1. operational `>`: `set cli screen-length 0` (Netmiko does this itself) → `configure private`
  2. `set ...` lines (one statement per line)
  3. `show | compare` (diff for the job record / preview) — [U] exact text, standard Junos idiom
  4. `commit check` → stop on any `error:`
  5. `commit confirmed 5 comment "netconfig job <id>"` — [U] combining `confirmed` and `comment` in one command is standard Junos but was not read verbatim
  6. exit to operational mode? **No – stay in config mode** and run verify commands with the `run` prefix (`run show vlans`) [U], or exit with `exit` only *after* the final confirm, because exiting private mode with uncommitted changes discards them (harmless after a commit).
  7. `commit` (confirms; or `commit check`) → `exit`
  8. On failed verification: `rollback 1` + `commit` to undo immediately (rollback 1 = config before the confirmed commit) [U – standard practice, inferred from rollback doc], or simply disconnect and let the timer expire.
- [U] Entering `configure private` prints `warning: uncommitted changes will be discarded on exit`; if the *shared* candidate already has uncommitted changes by another user, `configure private` fails with `error: shared configuration database modified` – treat both as recognisable strings; the second must abort the job ("someone else is editing").
- [U] Exiting config mode with uncommitted changes prompts `The configuration has been changed but not committed` followed by `Exit with uncommitted changes? [yes,no] (yes)` (shared mode) / `Discard uncommitted changes? [yes,no] (yes)` (private/exclusive). Exact prompt text not confirmed this session – the driver should pattern-match `[yes,no]` and answer explicitly.
- The NETCONF conflict does not matter for a Netmiko CLI driver, but if PyEZ/NETCONF is added later, use `configure exclusive` for confirmed commits.

### Gaps
- Exact exit prompt strings for private mode and the `shared configuration database modified` error were not visible on the fetched official page (code blocks stripped). Verify on vJunos.

## 2. Hostname, domain, banner, web management, save semantics

### Takeaway
`set system host-name X`, `set system domain-name X`, `set system login message "text"`,
`delete system services web-management`. Junos has no "write memory": a successful `commit` is persistent.

### Cited Findings
- [P] Commit activates the candidate config; previous committed configs are retained as rollback files (`rollback N`). — [rollback](https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/command/rollback.html); [commit](https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/command/commit.html)

### Inferences
- [U] `set system host-name SW1`; `set system domain-name example.local`; `set system login message "Authorized access only"`; `set system login announcement "..."` (post-login); `delete system services web-management` (J-Web; present on SRX and older EX; may not exist on vJunos-switch – `delete` of a non-existent statement returns `warning: statement not found`).
- `save_command()` for Junos should return `None` (commit is the save). Note Junos config-mode `save <file>` writes a file – it is NOT persistence; do not use.
- [U] Virtual Chassis / dual-RE EX: `set system commit synchronize` or `commit synchronize` so both REs get the config.
- **Denylist conflict (important):** CLAUDE.md §8.5 denylists `delete`. In Junos, `delete <hierarchy>` is the normal way to remove config (e.g. `delete system services web-management`). The Junos driver needs an OS-specific denylist: block `delete` only with no argument / at `[edit]` top (`delete` alone wipes the whole candidate), `delete system root-authentication`, `delete system login user <self>`, `delete interfaces <mgmt>`, `load factory-default`, `load override`, `request system reboot|halt|power-off|zeroize`, `request system software ...`, `rollback` (as a user custom command), `deactivate`/`disable` on the management interface.

### Gaps
- No official page with the host-name/domain-name/login message command text was fetched this session.

## 3. VLANs, access ports, interface-range, edge ports, port security (EX ELS / vJunos-switch)

### Takeaway
ELS: `set vlans NAME vlan-id N`; access: `set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode access` + `... vlan members NAME`. The pre-ELS `port-mode` statement was replaced by `interface-mode`.

### Cited Findings
- [V] (community study guide) `set vlans SALES vlan-id 10`; `set vlans ENGINEERING vlan-id 20` — [open-exam-prep JNCIS-ENT IRB](https://open-exam-prep.com/study-guides/jncis-ent/vlans-inter-vlan-routing/irb-configuration-packet-walk) (secondary source; matches Juniper ELS docs' "Create the VLAN by setting a unique VLAN name and configuring the VLAN ID" step in [Layer 2 Networking (ELS)](https://www.juniper.net/documentation/en_US/junos/topics/task/configuration/bridging-vlans-ex-series-cli-els.html))
- [V] Access example: `set interfaces ge-0/0/0 unit 0 family ethernet-switching vlan members 600` with `interface-mode access` — [Mapping OpenConfig VLAN Commands to Junos Configuration](https://www.juniper.net/documentation/us/en/software/junos/open-config/topics/concept/openconfig-vlan-mapping.html) (`vlan members` accepts a VLAN name or ID)
- [P] ELS change table: `port-mode` replaced by `interface-mode`; native VLAN moved from `family ethernet-switching` to the physical interface level. — [Getting Started with ELS (13.2)](https://www.juniper.net/documentation/en_US/junos13.2/topics/task/configuration/getting-started-els.html); [interface-mode statement](https://www.juniper.net/documentation/en_US/junos13.2/topics/reference/configuration-statement/interface-mode-edit-interfaces.html)
- [V] ELS replacement for allowed-mac port security: `set interfaces ge-0/0/2 unit 0 accept-source-mac mac-address 00:05:85:3A:82:8...` (MAC truncated on page); L2 global mode on SRX: `set protocols l2-learning global-mode (transparent-bridge | switching)`. — [Layer 2 Networking](https://www.juniper.net/documentation/en_US/junos/topics/task/configuration/bridging-vlans-ex-series-cli-els.html)
- [P] Interface ranges: `member-range` takes a start and end interface under `[edit interfaces interface-range <name>]`; expansion creates interface objects not explicitly defined. — [Interface Ranges (EX)](https://www.juniper.net/documentation/us/en/software/junos/interfaces-ethernet-switches/topics/topic-map/switches-interface-range.html); [member-range](https://www.juniper.net/documentation/en_US/junos/topics/reference/configuration-statement/member-range-edit-interfaces-ex-series.html)
- [P] RSTP edge: `edge` under `protocols rstp interface <name>`; an edge port that receives a BPDU becomes non-edge. — [RSTP example (QFX/EX)](https://www.juniper.net/documentation/en_US/junos/topics/example/stp-rstp-qfx-series.html)

### Inferences
- [U] Full generator lines (ELS):
  - `set vlans V10 vlan-id 10` (optionally `set vlans V10 description "..."`)
  - `set interfaces ge-0/0/1 description "PC-1"`
  - `set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode access`
  - `set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members V10`
  - Range: `set interfaces interface-range ACCESS-1 member-range ge-0/0/1 to ge-0/0/10` or `set interfaces interface-range ACCESS-1 member ge-0/0/[1-10]` then `set interfaces interface-range ACCESS-1 unit 0 family ethernet-switching interface-mode access` / `... vlan members V10`
  - Edge (portfast): `set protocols rstp interface ge-0/0/1 edge` (+ optional `set protocols rstp bpdu-block-on-edge`). Note: vJunos-switch/EX default config usually has `protocols rstp interface all`, verify.
  - MAC limit (port-security, ELS): `set switch-options interface ge-0/0/1.0 interface-mac-limit 2 packet-action drop` – **flag:** whether the ELS hierarchy wants `ge-0/0/1` or `ge-0/0/1.0`, and whether `packet-action` sits under `interface-mac-limit`, changed between releases; lab-verify. Mark this feature experimental.
- VLAN naming: Junos VLANs are named; the ELS default VLAN is named `default` (vlan-id 1). Generator should name VLANs from the plan's validated name (`[A-Za-z0-9_-]{1,32}` fits) and avoid `default`. Convention `V<id>` or the user's name.
- An interface that has `family ethernet-switching` cannot also have `family inet` on the same unit; if the plan converts a port, the generator must `delete interfaces ge-0/0/X unit 0 family ethernet-switching` first (which collides with the generic denylist – see §2).

### Gaps
- No official page with the exact VLAN-name length/character rules was found.
- Exact ELS `switch-options ... interface-mac-limit` hierarchy not confirmed.

## 4. Trunk ports and native VLAN (ELS)

### Takeaway
`interface-mode trunk` + `vlan members [ V10 V20 ]` on unit 0; native VLAN is set on the **physical** interface: `set interfaces ge-0/0/24 native-vlan-id 10`, and the native VLAN must also be a member.

### Cited Findings
- [P] Procedure: "set the interface mode to trunk, configure the native VLAN ID, and specify that the logical interface that will receive the untagged data packets is a member of the native VLAN"; untagged packets are dropped on trunks with no native VLAN. — [Configuring the Native VLAN Identifier (ELS, 13.2)](https://www.juniper.net/documentation/en_US/junos13.2/topics/task/configuration/bridging-native-vlan-id-ex-series-cli-els.html); [native-vlan-id statement (current)](https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/native-vlan-id-edit-interfaces-qfx-series.html)
- [P] Juniper ELS example connects access→distribution with a trunk uplink `ge-0/2/0` (trunk, native VLAN, vlan members), VLAN `sales` (100) → `irb.0`, `support` (200) → `irb.1`. — [Example: Connecting an Access Switch to a Distribution Switch (ELS)](https://www.juniper.net/documentation/en_US/junos13.2/topics/example/bridging-ex-series-connecting-access-to-distribution-switch-els.html)
- [P] Logical interface trunk mode task page. — [Configuring a Logical Interface for Trunk Mode](https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/task/interfaces-configuring-a-logical-interface-for-trunk-mode.html)

### Inferences
- [U] Lines: `set interfaces ge-0/0/24 unit 0 family ethernet-switching interface-mode trunk`; `set interfaces ge-0/0/24 unit 0 family ethernet-switching vlan members [ V10 V20 V99 ]` (bracket list; or one `vlan members X` line per VLAN — both valid set syntax; one-per-line is safer for parsing/denylist); `set interfaces ge-0/0/24 native-vlan-id 99` (number, not name).
- `vlan members all` exists [U]; the generator should always emit an explicit list.

### Gaps
- The exact current-release command block could not be extracted from the HPE-hosted page.

## 5. IRB (SVI) and routed interfaces

### Takeaway
`set interfaces irb unit 10 family inet address 192.168.10.1/24` + `set vlans V10 l3-interface irb.10`. Routed port: `set interfaces ge-0/0/0 unit 0 family inet address A.B.C.D/LEN`.

### Cited Findings
- [V] (community) `set interfaces irb unit 10 family inet address 192.168.10.1/24`; `set vlans SALES l3-interface irb.10`; omitting `l3-interface` leaves the IRB disconnected; matching unit number to VLAN ID is best practice but not required. — [open-exam-prep IRB packet walk](https://open-exam-prep.com/study-guides/jncis-ent/vlans-inter-vlan-routing/irb-configuration-packet-walk)
- [P] Official ELS IRB task page and `l3-interface` statement. — [Configuring IRB Interfaces on EX (ELS)](https://www.juniper.net/documentation/en_US/junos13.2/topics/task/configuration/bridging-integrated-routing-briding-interfaces-ex-series-cli-els.html); [l3-interface (vlans)](https://www.juniper.net/documentation/en_US/junos13.2/topics/reference/configuration-statement/l3-interface-edit-vlans-qfx-series.html)

### Inferences
- Use `irb.<vlan_id>` convention. Pre-ELS used `vlan.N` + `l3-interface vlan.N`; never emit that for ELS.
- [U] Routed: `set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/30`; description at physical level `set interfaces ge-0/0/0 description "..."`. On SRX the interface must also be in a security zone (see §7) or traffic is dropped.

### Gaps
- None material beyond lab confirmation.

## 6. DHCP server (EX and SRX – JDHCP "dhcp-local-server")

### Takeaway
Pool under `[edit access address-assignment pool]`, server group under `[edit system services dhcp-local-server]`; the group does not name the pool – pools are matched by the serving interface's subnet (ip-address-first). Legacy `system services dhcp pool` is deprecated (JDHCP only from 15.1X49-D60 / 17.3R1 on SRX).

### Cited Findings
- [V] From "Configuring a Switch as a DHCP Server (CLI Procedure)" (ELS):
  - `set system services dhcp-local-server group server1 interface ge-0/0/1`
  - `set access address-assignment pool pool1 family inet network 20.1.1.0/24`
  - `set access address-assignment pool pool1 family inet range range1 low 20.1.1.101`
  - `set access address-assignment pool pool1 family inet range range1 high 20.1.1.110`
  - `set access address-assignment pool pool1 family inet dhcp-attributes router 20.1.1.254`
  - `set access address-assignment pool pool1 family inet dhcp-attributes maximum-lease-time 43200` (page shows "43,200")
  — [dhcp-server-cli-els (13.2, HPE host)](https://networkingdocs.hpe.com/documentation/en_US/junos13.2/topics/task/configuration/dhcp-server-cli-els.html)
- [P] Pool example form: `pool acmenetwork { family inet { network 192.168.1.0/24; range r1 { low 192.168.1.10; high 192.168.1.20; } } }`; `excluded-address 10.3.3.33;` inside a pool's `family inet`. "You can exclude one or more addresses within the range. This statement is optional." Only one address range per pool is supported (switch section). — [DHCP Server Options](https://www.juniper.net/documentation/us/en/software/junos/dhcp/topics/topic-map/dhcp-serever-options.html)
- [P] `dhcp-attributes` (inside pool family inet) carries options such as `name-server`, `router`, `domain-name`, `maximum-lease-time`. — [dhcp-attributes (Address-Assignment Pools)](https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/dhcp-attributes-edit-access.html)
- [P] Default pool match is `ip-address-first` (changeable via `pool-match-order`); "The extended DHCP local server and the address-assignment pools used by the server must be configured in the same logical system and routing instance." — [DHCP Client Attribute and Address Assignment](https://www.juniper.net/documentation/us/en/software/junos/subscriber-mgmt-sessions/topics/topic-map/dhcp-client-address-attribute-assignment.html); [Group-specific DHCP configurations](https://www.juniper.net/documentation/us/en/software/junos/dhcp/topics/topic-map/dhcp-common-configuration-group-interfaces-applying.html)
- [P] SRX: min local server config applies to SRX300/320/340/345/550M/1500; "the legacy DHCPD (DHCP daemon) configuration on all SRX Series Firewalls is being deprecated"; from 15.1X49-D60 and 17.3R1 only the new JDHCP CLI is supported. — [DHCP Server Configuration](https://www.juniper.net/documentation/us/en/software/junos/dhcp/topics/topic-map/dhcp-server-configuration.html)

### Inferences
- [U] Remaining attribute lines: `set access address-assignment pool P10 family inet dhcp-attributes name-server 8.8.8.8` (one line per server); `... dhcp-attributes domain-name example.local`; `... family inet excluded-address 192.168.10.1`; `... family inet excluded-range R1 low X high Y` (excluded-range availability is release-dependent — flag).
- Serving interface for VLAN DHCP is the IRB: `set system services dhcp-local-server group G10 interface irb.10`. Pool network must equal the IRB subnet (ip-address-first match) – the validator's "gateway inside pool" check maps to `router` = IRB address.
- Excluded addresses approach: prefer a `range` that skips the gateway/static block (e.g. .100–.200) rather than excluded-address, since range is verified [V].
- SRX additionally needs `set security zones security-zone trust interfaces irb.10 host-inbound-traffic system-services dhcp` [U] or DHCP requests are dropped by the zone.
- Verification: `show dhcp server binding` [U].

### Gaps
- `excluded-range` syntax/version not confirmed. name-server/domain-name exact lines not read verbatim.

## 7. NAT (SRX only)

### Takeaway
Interface source NAT on SRX = `set security nat source rule-set RS from zone trust` / `to zone untrust` / `rule R match source-address 0.0.0.0/0` / `then source-nat interface`, plus a trust→untrust security policy. No pool is needed. EX switches: no NAT (not found documented – treat as unsupported).

### Cited Findings
- [V] (Juniper Japan PDF) `set security nat source rule-set 1 from zone trust`, `set security nat source rule-set 1 to zone untrust`, rule `1A` `match source-address 0.0.0.0/0`, `then source-nat interface`. — [Juniper NAT guide (JP PDF)](https://www.juniper.net/assets/jp/jp/local/pdf/others/nat.pdf)
- [P] Official steps: "Create a source NAT rule set", "Configure a rule that matches packets and translates the source address to the address of the egress interface", "Configure a security policy that allows traffic from the trust zone to the untrust zone." "No source NAT pool is required for source NAT using an egress interface." Page scope: SRX Series Firewalls only. — [Source NAT](https://www.juniper.net/documentation/us/en/software/junos/nat/topics/topic-map/nat-source.html)
- [P] Rule-set matching precedence: interface, then zone, then routing instance. — (search summary of) [Juniper NAT guide (JP PDF)](https://www.juniper.net/assets/jp/jp/local/pdf/others/nat.pdf)
- (Community) Complete `rule-set` + `rule` example; all NAT is done in NAT policy. — [community: SRX firewall NAT or route interface](https://community.juniper.net/discussion/srx-firewall-nat-or-route-interface)

### Inferences
- [U] Full SRX block:
  - `set security nat source rule-set TRUST-TO-UNTRUST from zone trust`
  - `set security nat source rule-set TRUST-TO-UNTRUST to zone untrust`
  - `set security nat source rule-set TRUST-TO-UNTRUST rule NAT-ALL match source-address 192.168.10.0/24`
  - `set security nat source rule-set TRUST-TO-UNTRUST rule NAT-ALL then source-nat interface`
  - `set security policies from-zone trust to-zone untrust policy ALLOW-OUT match source-address any destination-address any application any` then `... then permit`
  - zones: `set security zones security-zone untrust interfaces ge-0/0/0.0`, `set security zones security-zone trust interfaces irb.10`
- SRX300 factory-default already contains trust→untrust interface NAT and policy – generator should detect/merge, not duplicate.
- Capability matrix: `nat` true only for an `junos_srx` os_id; false for `junos_els` (EX/vJunos-switch). Separate os_ids are recommended because SRX also requires zones/policies for any routed traffic.

### Gaps
- No official statement "EX does not support NAT" was found; this is an inference from NAT docs scoping to SRX/MX.

## 8. Static routes, OSPF, BGP, EIGRP

### Takeaway
`set routing-options static route P/L next-hop X` (+ `preference N`); OSPF `set protocols ospf area 0.0.0.0 interface ge-0/0/0.0` (+ `passive`), `set routing-options router-id X`; BGP needs `routing-options autonomous-system`, a group with `type external peer-as N neighbor X`, and an export policy to advertise networks. EIGRP is not a Junos protocol.

### Cited Findings
- No official page for these statements was fetched this session (tool budget). The statements below are standard Junos and should be lab-verified.

### Inferences
- [U] Static: `set routing-options static route 0.0.0.0/0 next-hop 203.0.113.1`; `set routing-options static route 10.20.0.0/16 preference 10` (static default preference = 5); per-next-hop: `qualified-next-hop X preference N`; null route: `... discard`.
- [U] OSPF: `set routing-options router-id 1.1.1.1`; `set protocols ospf area 0.0.0.0 interface ge-0/0/0.0`; `set protocols ospf area 0.0.0.0 interface irb.10 passive`; `set protocols ospf area 0.0.0.0 interface lo0.0 passive`. Always include the unit (`.0`). Area may be written `0` or `0.0.0.0` (normalised to dotted).
- [U] BGP minimal:
  - `set routing-options autonomous-system 65001`
  - `set protocols bgp group EBGP-ISP type external`
  - `set protocols bgp group EBGP-ISP peer-as 65002`
  - `set protocols bgp group EBGP-ISP neighbor 198.51.100.1 description "ISP-A"`
  - `set policy-options policy-statement BGP-EXPORT term NETS from route-filter 192.168.10.0/24 exact`
  - `set policy-options policy-statement BGP-EXPORT term NETS then accept`
  - `set policy-options policy-statement BGP-EXPORT term REJECT then reject` (stops transit leaking of other BGP routes)
  - `set protocols bgp group EBGP-ISP export BGP-EXPORT`
  - The prefix must be active in inet.0 (direct/static); for an aggregate add `set routing-options static route 192.168.0.0/16 discard`. Newer releases may implement RFC 8212 (EBGP default reject without policy) – version-dependent, flag.
- EIGRP: Cisco-originated protocol; Junos has no `protocols eigrp` hierarchy → driver must raise "EIGRP not supported on Junos".

### Gaps
- Official citations for routing-options/OSPF/BGP/policy syntax and for "no EIGRP" were not retrieved; RFC 8212 default behaviour per Junos release unknown.

## 9. Local users, SSH, root-authentication (non-interactive passwords)

### Takeaway
`plain-text-password` is **interactive** (prompts to enter and confirm), so scripted pushes should send `encrypted-password "<hash>"` with a pre-computed crypt hash. Never pass a plain-text password to `encrypted-password` – you lock yourself out.

### Cited Findings
- [P] Predefined classes: `super-user` (all), `operator` (clear, network, reset, trace, view), `read-only` (view), `unauthorized` (none). — [User Accounts](https://www.juniper.net/documentation/us/en/software/junos/user-access/topics/topic-map/junos-os-user-accounts.html)
- [P] "If you configure the plain-text-password option, you receive a prompt to enter and confirm the password." "Plain-text passwords are hidden and marked as ## SECRET-DATA in the configuration." — [User Accounts](https://www.juniper.net/documentation/us/en/software/junos/user-access/topics/topic-map/junos-os-user-accounts.html)
- [P] Caution: if you configure `encrypted-password` with a plain-text password (or blank quotes) you "will not be able to log in to the device as this user"; "Do not use the encrypted-password option unless the password is already encrypted." — [User Accounts](https://www.juniper.net/documentation/us/en/software/junos/user-access/topics/topic-map/junos-os-user-accounts.html)
- [P] Root password page (root-authentication). — [Root Password](https://www.juniper.net/documentation/us/en/software/junos/user-access/topics/topic-map/user-access-root-password.html)
- (Community) Scripts using `plain-text-password` must answer the prompts; passwords with spaces were rejected; Juniper's own junos-mcp-server test generates a crypt hash and sets `encrypted-password`. — [Thwack thread](https://thwack.solarwinds.com/discussion/49527/change-config-templates-trying-to-write-a-script-for-juniper-devices-to-update-local-accounts-and-passwords); [Juniper junos-mcp-server test](https://glama.ai/mcp/servers/@Juniper/junos-mcp-server/blob/a0915d6d0c215363bf14c43b66473774508e9e01/test/test_mcp_client_set_user_password.py)

### Inferences
- [U] Lines: `set system login user netadmin class super-user`; `set system login user netadmin authentication encrypted-password "$6$<salt>$<hash>"`; `set system root-authentication encrypted-password "$6$..."`; `set system services ssh protocol-version v2` (on recent releases v1 is removed and the statement may be absent/no-op – version-dependent); `set system services ssh root-login deny`; optional `authentication ssh-ed25519 "<pubkey>"`.
- [U] Factory-default/vJunos-switch refuses the first commit without `root-authentication` (`Missing mandatory statement: 'root-authentication'`) — relevant to console bootstrap.
- **Windows implementation flag:** Python's `crypt` module is Unix-only (and removed in 3.13), so on Windows the backend needs its own SHA-512-crypt (`$6$`) implementation or a library such as passlib → this is a new library and needs the author's approval (CLAUDE.md §10). Hash line must be masked (`encrypted-password` is already on the mask list).
- Alternative: answer `New password:` / `Retype new password:` prompts via Netmiko `send_command_timing` – more fragile; avoid.

### Gaps
- Exact supported hash formats list ($1$/$5$/$6$) per release not confirmed.

## 10. CLI error strings (for error_patterns())

### Takeaway
Stop on any of: `syntax error`, `unknown command`, `missing argument`, `invalid value`, `error:`, `commit failed`, `configuration check-out failed`, `invalid interface type`, `is not a valid`, and on exit/commit prompts that were not expected.

### Cited Findings
- [P] Exclusive-mode confirmed-commit expiry error text "access has been revoked". — [Configure Command](https://www.juniper.net/documentation/us/en/software/junos/cli/topics/topic-map/configure-command.html)

### Inferences
- [U] Typical outputs: `syntax error, expecting <statement>.` / `syntax error.` (bad set line, caret `^` marks the position); `unknown command.` (operational typo); `missing argument.`; `invalid value`/`value ... is not within range`; commit failures print the hierarchy then `error: configuration check-out failed` (commit check) or `error: commit failed: (statements constraint check failed)`; `warning: statement not found` (delete of absent statement – treat as warning, not error). Successful commit prints `commit complete`; successful check prints `configuration check succeeds`. Netmiko's Juniper `commit()` checks for these success strings and raises on absence [U].
- Treat "warning:" lines as non-fatal but record them.

### Gaps
- An official consolidated list of CLI error strings was not found; collect real strings from vJunos during lab testing and freeze them in golden tests.

## 11. Verification show commands and automation interaction

### Takeaway
Use `show vlans`, `show ethernet-switching interface`, `show interfaces terse`, `show lldp neighbors`, `show version`, `show chassis hardware`, `show ospf neighbor`, `show bgp summary`, `show dhcp server binding`, `show configuration | display set`. For reliable parsing append `| display json` (or `| display xml`) instead of screen-scraping. Paging is disabled with `set cli screen-length 0` (Netmiko's Juniper driver does this at session start). From config mode, prefix operational commands with `run`.

### Cited Findings
- None fetched this session for show-command output formats.

### Inferences
- [U] Expected column headers (verify against lab output before writing parsers): `show vlans` → `Routing instance  VLAN name  Tag  Interfaces` (`*` marks active member); `show ethernet-switching interface` → `Logical interface / VLAN members / Tag / Tagging / Blocking`; `show interfaces terse` → `Interface Admin Link Proto Local Remote`; `show lldp neighbors` → `Local Interface  Parent Interface  Chassis Id  Port info  System Name`; `show version` → `Hostname:`, `Model:`, `Junos:` lines; `show chassis hardware` → `Item Version Part number Serial number Description` with `Chassis` row = serial; `show ospf neighbor` → `Address Interface State ID Pri Dead` (State `Full`); `show bgp summary` → per-peer line ending with `Establ` / state name; `show dhcp server binding` → `IP address Session Id Hardware address Expires State Interface`.
- `management_interface()`: run `show interfaces terse` and find the logical interface whose `Local` column contains `<mgmt_ip>/len` (vJunos/EX out-of-band is `em0`/`fxp0`/`me0`; in-band usually `irb.X` or `ge-.../.0`).
- Netmiko device_type `juniper_junos`; it enters `cli` if logged in as root at the shell, sets `set cli screen-length 0` and screen-width [U]. Its `config_mode()` accepts a `config_command` argument, so `configure private` can be used [U – verify Netmiko version in requirements.txt].

### Gaps
- Output formats are from general knowledge, not fetched docs; JSON output availability per release (14.2+) not confirmed this session.
