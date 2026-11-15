# HPE Aruba Networking AOS-CX CLI syntax reference (CX 6100 / 6300 / AOS-CX Simulator, 10.10–10.15)

> **How these notes were sourced.** The HPE techdocs site (arubanetworking.hpe.com/techdocs and www.arubanetworks.com/techdocs) returned HTTP 403 to automated fetches during this research. The full text came from two official HPE PDF guides hosted on third-party download sites, converted with pdftotext:
> - **[F1010]** *AOS-CX 10.10 Fundamentals Guide, 6300/6400 Switch Series* (HPE, Aug 2022, Edition 2): https://www.bhphotovideo.com/lit_files/1146748.pdf (retailer copy of the official HPE PDF; page numbers are the guide's own).
> - **[C6100]** *AOS-CX 10.10 Command-Line Interface Guide, 6000/6100 Switch Series* (HPE, Apr 2023, Version 4): https://download.axilogi.com/HPE/Manual/HPE_6000_a_6100_MCG.pdf (distributor copy of the official HPE PDF).
>
> Items cited to techdocs URLs came from **search-engine extracts** of those official pages, not full-page reads, so check them once against the page itself. Every command page in F1010 and C6100 lists "10.07 or earlier" as the release that introduced it, so the syntax should hold for 10.10–10.15. Spot-check it on the AOS-CX Simulator at the target release anyway.
>
> **Contexts** (as F1010/C6100 name them): `Manager (#)` = privileged exec (`switch#`). `config` = `switch(config)#`. `config-if` = `switch(config-if)#`. `config-vlan-<id>` = `switch(config-vlan-10)#`. `config-if-vlan` = `switch(config-if-vlan)#`. Operator context is `>`.

## 1. Safe change window: checkpoint auto mode, rollback, checkpoints

### Takeaway
`checkpoint auto <1-60>` (Manager `#` context) starts a timer. If `checkpoint auto confirm` is not entered before it expires, the switch discards every change and restores the running config it had before auto mode. Confirming creates a checkpoint named `AUTO<YYYYMMDDHHMMSS>` and ends auto mode. The guides do not describe an explicit "abort now" command. For an immediate rollback, take a named checkpoint before applying and use `checkpoint rollback <name>`. `write memory` is a separate step.

### Cited Findings
- Syntax: `checkpoint auto <TIME-LAPSE-INTERVAL>`, where the interval is "the time lapse interval in minutes. Range: 1 to 60." Context **Manager (#)**, all platforms. — [F1010 p.178](https://www.bhphotovideo.com/lit_files/1146748.pdf); range also shown as `<1-60>` in CLI help on an 8320 — [Airheads community thread (community)](https://community.arubanetworks.com/discussion/aos-cx-8320-checkpoint-auto-minutes-failure-after-admin-disconnect)
- Description: "Starts auto checkpoint mode... the switch temporarily saves the runtime configuration as a checkpoint only for the specified time lapse interval. Configuration changes must be saved before the interval expires, otherwise the runtime configuration is restored from the temporary checkpoint." — [F1010 p.178](https://www.bhphotovideo.com/lit_files/1146748.pdf)
- On timeout: "If you do not execute the checkpoint auto confirm command within the specified time, all configuration changes you made are discarded and the running configuration reverts to the state it was before entering checkpoint auto mode." Purpose: auto mode "configures the switch with failover support, causing it to automatically revert to a previous configuration if it becomes inoperable or inaccessible due to configuration changes". — [F1010 p.178 "Checkpoint auto mode"](https://www.bhphotovideo.com/lit_files/1146748.pdf); same text in 10.17 — [techdocs 10.17 Checkpoint auto mode](https://arubanetworking.hpe.com/techdocs/AOS-CX/10.17/HTML/fundamentals_8400/Content/Chp_Cfg_FW_mgt/che-aut-mod.htm)
- Exact device output, confirmed path:
  ```
  switch# checkpoint auto 20
  Auto checkpoint mode expires in 20 minute(s)
  switch# WARNING Please "checkpoint auto confirm" within 2 minutes
  switch# checkpoint auto confirm
  checkpoint AUTO20170801011154 created
  ```
  Exact device output, timeout path:
  ```
  switch# checkpoint auto 20
  Auto checkpoint mode expires in 20 minute(s)
  switch# WARNING Please "checkpoint auto confirm" within 2 minutes
  WARNING: Restoring configuration. Do NOT add any new configuration.
  Restoration successful
  ```
  — [F1010 pp.178–179](https://www.bhphotovideo.com/lit_files/1146748.pdf)
- `checkpoint auto confirm`: "Signals to the switch to save the running configuration used during the auto checkpoint mode. This command also ends the auto checkpoint mode." The generated checkpoint name format is `AUTO<YYYYMMDDHHMMSS>`. Context Manager (#). — [F1010 p.179](https://www.bhphotovideo.com/lit_files/1146748.pdf); 10.14 page: [techdocs 10.14 checkpoint auto](https://arubanetworking.hpe.com/techdocs/AOS-CX/10.14/HTML/fundamentals_6200/Content/Chp_Cfg_FW_mgt/Chk_cmds/che-aut.htm). One search extract of the 10.14 page rendered the format as `AUTO <YYYYMMDDHHSS>`. F1010 gives `AUTO<YYYYMMDDHHMMSS>` and the example `AUTO20170801011154`, which is 14 digits.
- `checkpoint rollback {<CHECKPOINT-NAME> | startup-config}` "Applies the configuration from a pre-existing checkpoint or the startup configuration to the running configuration." Device output is `Success`. Context Manager (#). "All previous configurations are lost after the execution of this command." — [F1010 pp.177, 184](https://www.bhphotovideo.com/lit_files/1146748.pdf); [techdocs 10.15 checkpoint rollback](https://arubanetworking.hpe.com/techdocs/AOS-CX/10.15/HTML/fundamentals_8400/Content/Chp_Cfg_FW_mgt/Chk_cmds/che-rol.htm)
- `copy checkpoint <CHECKPOINT-NAME> {running-config | startup-config}` copies a checkpoint into the running or startup config. Output `Success`. — [F1010 p.186](https://www.bhphotovideo.com/lit_files/1146748.pdf)
- `copy running-config {startup-config | checkpoint <CHECKPOINT-NAME>}`: checkpoint names "can be alphanumeric. It can also contain underscores (_) and dashes (-)." "Do not start the checkpoint name with CPC because it is used for system-generated checkpoints." Output `Success`. Context Manager (#). — [F1010 p.190](https://www.bhphotovideo.com/lit_files/1146748.pdf)
- System checkpoints are named `CPC<YYYYMMDDHHMMSS>` and created automatically 300 s after the last config change. Limits: 64 checkpoints in total, 32 user and 32 system; the newest system checkpoint replaces the oldest. — [F1010 p.177](https://www.bhphotovideo.com/lit_files/1146748.pdf)
- `show checkpoint <CHECKPOINT-NAME> [json]` shows a checkpoint's config. `show checkpoint` with no name lists checkpoints with name, type, writer, date and image version, and replaced `show checkpoint list all` in 10.08. — [F1010 p.196](https://www.bhphotovideo.com/lit_files/1146748.pdf); [techdocs 10.14 show checkpoint](https://arubanetworking.hpe.com/techdocs/AOS-CX/10.14/HTML/fundamentals_8400/Content/Chp_Cfg_FW_mgt/Chk_cmds/sho-che-lis.htm)
- `erase checkpoint <name>`, `erase checkpoint all` and `erase startup-config` exist in Manager (#). **Add them to the denylist.** — [F1010 p.195](https://www.bhphotovideo.com/lit_files/1146748.pdf)
- SSH disconnect during auto mode: a 2019 community thread on an 8320 running 10.04 reported that the auto revert did **not** happen if the admin disconnected before the timer expired. Aruba acknowledged it as a bug, and a later reply said it was fixed in 10.06.0010. — [Airheads thread (community)](https://community.arubanetworks.com/discussion/aos-cx-8320-checkpoint-auto-minutes-failure-after-admin-disconnect)
- A third-party blog gives the confirm command as `checkpoint confirm`. This **conflicts** with the official `checkpoint auto confirm`. — [Sikich blog (community)](https://www.sikich.com/insight/how-to-use-aruba-cx-checkpoint-auto-commands/) vs [F1010 p.179](https://www.bhphotovideo.com/lit_files/1146748.pdf)

### Inferences
- Rollback strategy for the driver: `copy running-config checkpoint NCS_<jobid>` (an explicit pre-change checkpoint whose name does not start with CPC), then `checkpoint auto N`, then `configure terminal` + changes, then exit to `#`, verify, then `checkpoint auto confirm`, then `write memory`. To roll back immediately, run `checkpoint rollback NCS_<jobid>`; otherwise let the timer expire.
- `checkpoint auto confirm` only creates the AUTO checkpoint and ends auto mode. No source says it writes startup-config, so the driver should still issue `write memory`.
- Auto mode is a switch-side timer that reverts "if it becomes inoperable or inaccessible", so it should cover changes made over SSH (Netmiko). The pre-10.06.0010 disconnect bug is the only reported exception, so set a minimum supported firmware of 10.06.0010 or later. The 10.10+ target range already satisfies this.
- `checkpoint auto` maps cleanly onto the brief's `rollback_strategy()`. Use something like `"checkpoint_auto"`, the AOS-CX analogue of Cisco's revert timer.

### Gaps
- No official source documents an explicit "cancel or abort auto mode now" command, or whether `checkpoint rollback <name>` is allowed while auto mode is active. Test this on the Simulator.
- No source says whether `write memory` is allowed or rejected while auto mode is active. Test it.
- The exact tabular output of `show checkpoint` with no name was not captured.

## 2. Hostname, domain name, banner, session timeout

### Takeaway
`hostname <1-32 chars, first char letter or digit>` and `ip dns domain-name <name> [vrf <vrf>]` are entered in config. Banners are interactive and multi-line: `banner motd <DELIMITER>`, then text, then the delimiter. `?` is not allowed as the delimiter. Idle timeout is `session-timeout <0-4320>` (legacy), or preferably `cli-session` followed by `timeout <min>`.

### Cited Findings
- `hostname <HOSTNAME>` / `no hostname [<HOSTNAME>]`: "The first character of the host name must be a letter or a number. Length: 1 to 32 characters. Default: switch". The prompt changes immediately (`myswitch(config)#`). `show hostname` shows it. — [F1010 p.333](https://www.bhphotovideo.com/lit_files/1146748.pdf)
- `ip dns domain-name <DOMAIN-NAME> [ vrf <VRF-NAME> ]`, length 1–256, default VRF `default`, context config. It is ignored if `ip dns domain-list` is defined. Example: `switch(config)# ip dns domain-name domain.com`. — [F1010 p.244](https://www.bhphotovideo.com/lit_files/1146748.pdf)
- `banner {motd | exec} <DELIMITER>`, context config. The text can span multiple lines, with a maximum of 4,095 characters. The delimiter "can be any non-whitespace character that does not have special meaning to the CLI, such as the caret (^). A question mark (?) is not permitted." The device prompts `Enter a new banner. Terminate the banner with the delimiter you have chosen.` with a `(banner-motd)#` continuation prompt (shown as `>>` in F1010) and replies `Banner updated successfully!`. Text after the delimiter on the same line is discarded. — [C6100 p.135](https://download.axilogi.com/HPE/Manual/HPE_6000_a_6100_MCG.pdf); [F1010 p.29](https://www.bhphotovideo.com/lit_files/1146748.pdf)
- Aruba Central template docs warn that `#` breaks `banner motd` in templates and recommend `@` or another special character. — search extract of [Configuring AOS-CX Using Templates](https://arubanetworking.hpe.com/techdocs/fedramp/webhelp/content/nms/aos-cx/get-started/prov-tmplt-cx.htm)
- `session-timeout <MINUTES>` (config): range 0–4320, 0 = never, default 30. `show session-timeout` prints `session-timeout: 30 minutes (Default)`. — [C6100 p.228](https://download.axilogi.com/HPE/Manual/HPE_6000_a_6100_MCG.pdf)
- `cli-session` (config) enters `config-cli-session`. Sub-commands: `[no] timeout <MINUTES>` (0–4320, default 30; "the recommended replacement for the session-timeout command"), `[no] max-per-user <1-5>`, `[no] tracking-range <1-30 days>`. It applies only to SSH and console logins, not REST. The running config renders it as `cli-session` / `    timeout 0`. — [C6100 p.232](https://download.axilogi.com/HPE/Manual/HPE_6000_a_6100_MCG.pdf); [F1010 p.197 example](https://www.bhphotovideo.com/lit_files/1146748.pdf)

### Inferences
- Banners are interactive: Netmiko must send `banner motd ^`, then the text lines, then a line ending in `^`, so it must not use `send_config_set` blindly with expect-prompt defaults. A simpler approach is to send the whole block with a single delimiter. Banner validation already forbids `^` and `#`. Choose a fixed delimiter such as `^` and forbid it, `?`, newlines beyond the allowed count, and `#` in the text.
- Generate `cli-session` + `timeout N` for 10.10+. Do not use the legacy `session-timeout`.

### Gaps
- Not verified whether the 10.13–10.15 guides still list `session-timeout`, or whether it is deprecated or hidden there.

## 3. VLANs, access ports, trunks, edge ports, port security

### Takeaway
Use `vlan N` → `name X` (1–32 characters, letters, digits, `_` and `-`). For access ports use `interface 1/1/N` → `no shutdown` → `no routing` → `vlan access N`. For trunks use `vlan trunk native N` + `vlan trunk allowed <list>`, where the list takes commas and dashes, e.g. `2-8,10`. Setting a native VLAN **auto-adds `vlan trunk allowed all`**, so always follow it with an explicit allowed list. `vlan trunk native N tag` tags the native VLAN.

### Cited Findings
- `vlan <VLAN-LIST>` (config) creates a VLAN and enters `config-vlan-<id>`. A range such as `vlan 2-8,10` does not enter a context. VLAN 1 cannot be deleted. Internal VLANs give `Ignoring the operation on internal VLAN(s) 3001.` The 6000/6100 support at most 512 VLANs. — [C6100 p.1311](https://download.axilogi.com/HPE/Manual/HPE_6000_a_6100_MCG.pdf)
- `name <VLAN-NAME>` (VLAN context): "Length: 1 to 32 alphanumeric characters, including underscore (_) and hyphen (-)". Names must be unique, and the default name is `VLAN <VLAN-ID>`. — [C6100 p.1299](https://download.axilogi.com/HPE/Manual/HPE_6000_a_6100_MCG.pdf)
- `vlan access <VLAN-ID>` (config-if): "VLANs can only be assigned to non-routed (Layer 2) interfaces. All interfaces are non-routed (Layer 2) by default when created. Use routing and no routing commands to move ports between Layer 3 and Layer 2 interfaces." `no vlan access` resets the port to VLAN 1. — [C6100 p.1313](https://download.axilogi.com/HPE/Manual/HPE_6000_a_6100_MCG.pdf); the same text appears in the techdocs CLI bank, whose example runs `no routing` before `vlan access 20` — [techdocs CLI-Bank 832x vlan access](https://arubanetworking.hpe.com/techdocs/AOS-CX/AOSCX-CLI-Bank/cli_832x/Content/Chp_VLANs/VLAN_cmds/vla-acc.htm)
- `routing` / `no routing` (config-if): "By default, routing is disabled on all interfaces." The platforms listed are 6300 and 6400. — [F1010 p.85](https://www.bhphotovideo.com/lit_files/1146748.pdf). A 6300 checkpoint example shows physical ports as `no shutdown` + `vlan access 1`, i.e. Layer 2. — [F1010 p.197](https://www.bhphotovideo.com/lit_files/1146748.pdf)
- **Conflicting report:** a community thread says the AOS-CX switch image on EVE-NG (the Simulator) had routed interfaces enabled by default, and that "not all aos-cx support that". — [Airheads thread (community)](https://airheads.hpe.com/discussion/aruba-cx-on-eve-ng-routing-between-vlan)
- `vlan trunk allowed [<VLAN-LIST> | all]` (config-if). The list is "a single ID, or a series of IDs separated by commas (2, 3, 4), dashes (2-4), or both (2-4,6)". Examples: `vlan trunk allowed 2,3,4`, `vlan trunk allowed 2-8,10`. "When the last VLAN is removed from a trunk interface, the interface continues to operate in trunk mode, and will trunk all the VLANs currently defined on the switch". The VLAN range is 1–4094 per the 10.13 page; one search extract of the 10.07 page said 4040. — [C6100 p.1314](https://download.axilogi.com/HPE/Manual/HPE_6000_a_6100_MCG.pdf); [techdocs 10.13 vlan trunk allowed](https://arubanetworking.hpe.com/techdocs/AOS-CX/10.13/HTML/l2_bridging_8400/Content/Chp_vlans/vlan_cmds/vla-tru-all.htm)
- `vlan trunk native <VLAN-ID>` (config-if; also LAG): the default native VLAN is 1. "When a native VLAN is defined, the switch automatically executes the vlan trunk allowed all command... To only allow specific VLANs on the trunk, issue the vlan trunk allowed command specifying only specific VLANs." — [C6100 p.1315](https://download.axilogi.com/HPE/Manual/HPE_6000_a_6100_MCG.pdf); [techdocs 10.15 L2 6300-6400 native VLAN](https://arubanetworking.hpe.com/techdocs/AOS-CX/10.15/HTML/l2_bridging_6300-6400/Content/Chp_vlans/asi-nat-vla-id-tru-int.htm)
- `vlan trunk native <VLAN-ID> tag`: "Only incoming packets that are tagged with the matching VLAN ID are accepted. Incoming packets that are untagged are dropped except for BPDUs. Egress packets are tagged." — [C6100 p.1316](https://download.axilogi.com/HPE/Manual/HPE_6000_a_6100_MCG.pdf). A search extract of the 10.16 L2 guide says native-VLAN traffic must also be explicitly allowed. — [techdocs 10.16 L2 guide PDF](https://arubanetworking.hpe.com/techdocs/AOS-CX/10.16/PDF/l2_bridging_4100i-5420-6000-6100-6200.pdf)
- `spanning-tree port-type {admin-edge|admin-network}` (config-if). The default is admin-network, which listens for BPDUs for 3 s and then auto-classifies the port. admin-edge goes straight to forwarding. — [C6100 p.707](https://download.axilogi.com/HPE/Manual/HPE_6000_a_6100_MCG.pdf)
- `port-access port-security {enable | disable}`, global (config) or per port (config-if). `port-access port-security client-limit <CLIENTS>`, default 1, range "1 to 32 (4100i, 6000, 6100)". The example shows `switch(config-if)# port-access port-security enable`, then `switch(config-if-port-security)# client-limit 24`. — [C6100 pp.928–929](https://download.axilogi.com/HPE/Manual/HPE_6000_a_6100_MCG.pdf)
- `show vlan [<VLAN-ID>]` output columns: `VLAN Name Status Reason Type Interfaces`, e.g. `2   UserVLAN1   up   ok   static 1/1/1,1/1/3,1/1/5`. — [C6100 p.1303](https://download.axilogi.com/HPE/Manual/HPE_6000_a_6100_MCG.pdf)
- `show interface 1/1/X` for a trunk includes `VLAN Mode: native-untagged`, `Native VLAN: 1` and `Allowed VLAN List: 1502-1505`. — [F1010 p.87–88](https://www.bhphotovideo.com/lit_files/1146748.pdf)

### Inferences
- **Always emit `no routing`** before `vlan access` / `vlan trunk` on physical ports, and `routing` before `ip address` on routed ports. This is harmless when it matches the default and protects against Simulator or platform differences.
- There is no `switchport mode` command. A port becomes a trunk when `vlan trunk ...` is applied. Generate in this order: `no routing`, then `vlan trunk native N`, then `vlan trunk allowed <list>`. The allowed list must come after native, because native resets allowed to `all`.
- The brief's VLAN-name regex `[A-Za-z0-9_-]{1,32}` matches the AOS-CX limit exactly.
- Port security: on the 6100 the documented range is 1–32. Mark the feature experimental for 6300, since its availability and range there were not verified.

### Gaps
- The 6300 port-security support and range were not found in a 6300 source.
- Whether the **AOS-CX Simulator** defaults ports to routed is supported only by a community post. Test it with `show running-config all` on the Simulator.

## 4. SVI, routed interface, static routes, default gateway

### Takeaway
SVI: `interface vlan N` (the VLAN must already exist; range 2–4094) → `ip address A.B.C.D/LEN`. Routed port: `interface 1/1/N` → `routing` → `ip address A.B.C.D/LEN`. Static route: `ip route A.B.C.D/LEN <next-hop|interface|reject|nullroute> [distance 1-255]` in config. No source mentions a global `ip routing` command. The management port uses `interface mgmt` with `ip static` and `default-gateway`.

### Cited Findings
- `interface vlan <VLAN-ID>` "Creates an interface VLAN also know as an SVI... The specified VLAN must already be defined on the switch." The range is 2–4094, the prompt is `switch(config-if-vlan)#`, and the command exists on both 6300 and 6100. — [F1010 p.74](https://www.bhphotovideo.com/lit_files/1146748.pdf); [C6100 p.421](https://download.axilogi.com/HPE/Manual/HPE_6000_a_6100_MCG.pdf)
- `ip address <IPV4-ADDR>/<MASK> [secondary]` uses CIDR only (`/24`, no dotted mask). Examples: `interface 1/1/1` → `routing` → `ip address 192.168.100.1/24`; `interface vlan 10` → `ip address 192.168.199.1/24`; `interface loopback 1` → `ip address 192.168.20.1/24`. — [F1010 p.74](https://www.bhphotovideo.com/lit_files/1146748.pdf)
- `ip route <DEST-IPV4-ADDR>/<NETMASK> {<NEXTHOP-ADDR> | <NEXTHOP-PORT-LAG-VLAN> | reject | nullroute}` "Adds an IPv4 static route on the default VRF." Distance form: `ip route <DEST>/<MASK> [<NEXT-HOP-IP-ADDR>|<INTERFACE>] distance <VALUE>`, default 1, range 1–255. Example: `ip route 10.0.2.0/24 20.0.0.2 distance 4`. — [C6100 pp.1184–1185](https://download.axilogi.com/HPE/Manual/HPE_6000_a_6100_MCG.pdf). The running-config form is `ip route 100.2.0.0/24 10.20.3.2`. — [F1010 p.127](https://www.bhphotovideo.com/lit_files/1146748.pdf)
- Limit on 4100i/5420/6000/6100/6200: "The number of IPv4 and IPv6 static routes that can be configured is limited to 512." — search extract of [techdocs 10.16 IP Routing 4100i-6200 PDF](https://arubanetworking.hpe.com/techdocs/AOS-CX/10.16/PDF/ip_route_4100i-5420-6000-6100-6200.pdf)
- The CX 6100 datasheet describes the 6100 as a Layer 2 series "with ... support for static routing". — search extract of a [CX 6100 datasheet copy](https://assets.printus.de/img/8/4/i1300740.pdf)
- Out-of-band management port (6300), from the startup-config example: `interface mgmt` / `no shutdown` / `ip static 10.6.9.15/24` / `default-gateway 10.6.9.1` (or `ip dhcp`). — [F1010 p.371](https://www.bhphotovideo.com/lit_files/1146748.pdf)

### Inferences
- In-band default gateway on an L2 switch managed through an SVI: use `ip route 0.0.0.0/0 <GW>`. No `ip default-gateway` command appeared in either guide; `default-gateway` exists only under `interface mgmt`.
- No `ip routing` global command needs to be generated. SVIs and routed ports route once they have an address. This is inferred: neither guide mentions `ip routing`.
- On the 6100, the `routing` command appears only in examples, and the C6100 guide has no `routing` command page. Treat 6100 routed physical ports as **unsupported**. Allow SVIs plus static routes only.

### Gaps
- No official statement was found about whether 6100 physical ports accept `routing`.
- The VRF form of static routes (`ip route ... vrf <name>`) was not extracted.

## 5. DHCP server

### Takeaway
On 6300 (IP Services Guide), the structure is `dhcp-server vrf default` → `pool NAME` → `range LOW HIGH [prefix-len N]`, `default-router ...`, `dns-server ...`, `lease ...`, `domain-name ...`, `exit` → `enable` (in the dhcp-server context). The **6000/6100 10.10 CLI guide contains no DHCP server commands**, only DHCP client and relay. Treat DHCP server as not supported on the 6100.

### Cited Findings
- Workflow: `dhcp-server vrf <VRF>` creates the VRF-level server, and `pool` enters the pool context. In the pool, set `range` (low/high IPv4, optional `prefix-len`), `lease`, up to four `default-router` addresses and up to four `dns-server` addresses. The 10.16 example: `range 10.0.0.1 10.0.0.100`, `lease 12:00:00`, `default-router ... 10.30.30.1 10.30.30.2`, `dns-server 125.0.0.1 125.0.0.2`, then `enable` at the server level. It also shows `domain-name` and `static-bind`. `authoritative` is optional. — search extracts of [techdocs 10.16 Configuring a DHCPv4 server on a VRF (6300-6400)](https://arubanetworking.hpe.com/techdocs/AOS-CX/10.16/HTML/ip_services_6300-6400/Content/Chp_DHCP/cnf-dhc-ser-vrf-10.htm), [techdocs 10.10 same page](https://www.arubanetworks.com/techdocs/AOS-CX/10.10/HTML/ip_services_83xx-9300-10000/Content/Chp_DHCP/cnf-dhc-ser-vrf-10.htm) and [techdocs 10.17 range](https://arubanetworking.hpe.com/techdocs/AOS-CX/10.17/HTML/ip_services_8400/Content/Chp_DHCP/DHCPv4_serv_cmds/ran-dhc-10.htm)
- Range warning: if `prefix-len` does not match the gateway interface's prefix length, clients may get a DHCP error. — same [range page](https://arubanetworking.hpe.com/techdocs/AOS-CX/10.17/HTML/ip_services_8400/Content/Chp_DHCP/DHCPv4_serv_cmds/ran-dhc-10.htm) (search extract)
- `lease {<TIME> | infinite}` with format DD:HH:MM and default 01:00:00. — search extract of [techdocs CLI-Bank lease](https://arubanetworking.hpe.com/techdocs/AOS-CX/AOSCX-CLI-Bank/cli_10000/Content/Chp_DHCP/DHCPv4_serv_cmds/lea-dhc-10.htm)
- The 6000/6100 10.10 CLI guide TOC lists "DHCP client commands" (`ip dhcp`) and "DHCPv4 relay commands" (`dhcp-relay`), with no `dhcp-server` command pages. Its only text matches for "dhcp-server" are in `ipv6 helper-address ... all-dhcp-servers`. — [C6100](https://download.axilogi.com/HPE/Manual/HPE_6000_a_6100_MCG.pdf)
- The 6200 10.13 IP Services Guide TOC lists `dhcp-server vrf`, `pool`, `range`, `default-router` and `show dhcp-server`, so the 6200 supports it. — search extract of [techdocs 10.13 ip_services_6200 PDF](https://arubanetworking.hpe.com/techdocs/AOS-CX/10.13/PDF/ip_services_6200.pdf)
- A community lab guide covers a DHCP server on the AOS-CX Simulator. — [arubase.club Simulator DHCP lab (community)](https://oss.arubase.club/wp-content/uploads/2023/03/1.AOS-CX-Simulator-Lab-IPv4-DHCP-Lab-Guide.pdf)

### Inferences
- Capability matrix: dhcp = yes on 6300/Simulator, no on 6100.
- Proposed generator form, to be verified on the Simulator before golden files are frozen:
  ```
  dhcp-server vrf default
      pool <NAME>
          range <LOW> <HIGH> [prefix-len <N>]
          default-router <GW>
          dns-server <DNS1> [<DNS2>]
          domain-name <DOMAIN>
          lease <DD:HH:MM>
          exit
      enable
  ```

### Gaps
- **The exact `default-router` syntax is unconfirmed.** One extract rendered it as `default-router ip 10.30.30.1 10.30.30.2`, which may be a rendering artefact. Read the 10.14/10.15 `default-router` page or test it.
- The `lease` format is ambiguous: the extract says DD:HH:MM, yet the example is `12:00:00` and the default `01:00:00`. Verify it.
- The `show dhcp-server` output format was not captured.

## 6. NAT and EIGRP

### Takeaway
Neither guide read contains any NAT (`ip nat`) or EIGRP command. Treat both as **not supported on AOS-CX switches**, and make the driver raise "not supported on AOS-CX".

### Cited Findings
- Full-text search of the 6000/6100 10.10 CLI guide found 0 matches for "ip nat", "eigrp", "router ospf" and "router bgp". — [C6100](https://download.axilogi.com/HPE/Manual/HPE_6000_a_6100_MCG.pdf)
- Full-text search of the 6300/6400 10.10 Fundamentals Guide found 0 matches for "eigrp" and " nat ". This guide does not cover routing protocols. — [F1010](https://www.bhphotovideo.com/lit_files/1146748.pdf)

### Inferences
- EIGRP is Cisco-originated, and no AOS-CX guide title or TOC seen in this research lists it. The AOS-CX IP Routing Guides list static, OSPFv2/v3 and BGP.

### Gaps
- No HPE document was found that explicitly says "NAT is not supported" on 6300. The 6300 IP Routing and IP Services guides were not text-searchable here. This is absence of evidence, not an explicit statement.

## 7. OSPFv2

### Takeaway
Configure `router ospf 1` → `router-id A.B.C.D` → `area 0.0.0.0` (config), then on each interface `ip ospf 1 area 0.0.0.0` and optionally `ip ospf passive`, or `passive-interface default` in the router context. OSPFv2 is **not supported on 6000/6100** per the 10.14 and 10.16 guides; it is supported on 6200 and 6300.

### Cited Findings
- Running-config rendering on a 6300: `router ospf 1` / `    router-id 1.63.63.1` / `    area 0.0.0.0`. — [F1010 p.371](https://www.bhphotovideo.com/lit_files/1146748.pdf)
- Interface command `ip ospf <PROCESS-ID> area <AREA-ID>`, e.g. `ip ospf 1 area 1`. The area may be given as an integer or in dotted IPv4 form, e.g. `0.0.0.0`. `ip ospf passive` makes the interface "participate in OSPF without forming adjacencies". — search extract of [techdocs 10.13 IP Routing 4100i-6200 PDF](https://arubanetworking.hpe.com/techdocs/AOS-CX/10.13/PDF/ip_route_4100i-6000-6100-6200.pdf)
- `passive-interface default` is entered in the OSPF router context. — [techdocs 10.15 Configuring all OSPF interfaces as passive](https://arubanetworking.hpe.com/techdocs/AOS-CX/10.15/HTML/ip_route_6300-6400-8100-83xx-9300-10000/Content/Chp_OSPFv2/cnf-pas-osp-int.htm) (search extract)
- "OSPFv2 is not supported on the 6000 and 6100 Switch Series." — search extracts of [techdocs 10.14 IP Routing 4100i-6200 PDF](https://arubanetworking.hpe.com/techdocs/AOS-CX/10.14/PDF/ip_route_4100i-6000-6100-6200.pdf) and [10.16](https://arubanetworking.hpe.com/techdocs/AOS-CX/10.16/PDF/ip_route_4100i-5420-6000-6100-6200.pdf). C6100 (10.10) has no `router ospf` command. — [C6100](https://download.axilogi.com/HPE/Manual/HPE_6000_a_6100_MCG.pdf)
- `show ip ospf [PROCESS-ID] neighbors [<neighbor-id> | interface ... | detail | summary]`. Sample output shows process ID 1 in VRF default with neighbor `2.2.2.2` in state `FULL/DR` on interface `1/1/1`; columns are neighbor ID, priority, state, neighbor address and interface. — search extract of [techdocs 10.15 show ip ospf neighbors](https://arubanetworking.hpe.com/techdocs/AOS-CX/10.15/HTML/ip_route_4100i-5420-6000-6100-6200/Content/Chp_OSPFv2/OSPFv2_cmds/sho-ip-osp-nei-10.htm)

### Inferences
- Generator form for 6300/Simulator:
  ```
  router ospf 1
      router-id <RID>
      area 0.0.0.0
  interface <IF>
      ip ospf 1 area 0.0.0.0
      ip ospf passive        (optional)
  ```
  Emit areas in dotted form to match the running config.
- The verify check parses `show ip ospf neighbors` for the neighbor ID and `FULL`.

### Gaps
- The exact column headers of `show ip ospf neighbors` were not captured.
- Whether the router context needs an explicit `enable` on some releases was not checked.

## 8. BGP

### Takeaway
`router bgp <ASN>` → `bgp router-id A.B.C.D` → `neighbor X remote-as N` → `address-family ipv4 unicast` → `neighbor X activate` (+ `network A.B.C.D/LEN`) → `exit-address-family`. BGP is a 6300 feature. The 6100 CLI guide has no BGP commands.

### Cited Findings
- Task list (10.16): define neighbors with `neighbor remote-as`, then `address-family`, then `neighbor activate`. The example is `router bgp 100` with a neighbor in AS 200, activated under `address-family ipv4 unicast`. — search extract of [techdocs 10.16 BGP configuration tasks](https://arubanetworking.hpe.com/techdocs/AOS-CX/10.16/HTML/ip_route_8400/Content/Chp_BGP/bas-bgp-cnf-10.htm)
- Example (10.13): `router bgp 20` / `bgp router-id 1.1.1.1` / `neighbor 192.168.13.1 remote-as 10` / `address-family ipv4 unicast` / `neighbor ... activate`. — search extract of [techdocs 10.13 BGP AS-path prepending](https://arubanetworking.hpe.com/techdocs/AOS-CX/10.13/HTML/ip_route_8400/Content/Chp_BGP/use-case-as-path-prep.htm)
- The `network` statement under `address-family ipv4 unicast` appears in an official AOS-CX 10.3 Multicast VRD and in a community Simulator BGP lab, but not on a techdocs page found here. — [AOS-CX 10.3 Multicast VRD (HPE-hosted)](https://higherlogicdownload.s3.amazonaws.com/HPE/MigratedAttachments/4E852383-EBEF-4921-82A7-8D6101A9DB0D-2-AOS-CX%2010_3%20Multicast%20VRD_Final.pdf); [arubase.club Simulator BGP lab (community)](https://arubase.club/wp-content/uploads/2023/03/5.AOS-CX-Simulator-Basic-BGP-Lab-Guide.pdf)
- A 10.14 BFD example rendered the address family as `address-family ipv4-unicast` (hyphenated). This is probably an extraction artefact; the other sources use `address-family ipv4 unicast`. — search extract of [techdocs 10.14 BFD for BGP](https://arubanetworking.hpe.com/techdocs/AOS-CX/10.14/HTML/high_availability/Content/Chp_BFD/cnf-bfd-bgp-10.htm)
- C6100 (10.10) has 0 matches for "router bgp". — [C6100](https://download.axilogi.com/HPE/Manual/HPE_6000_a_6100_MCG.pdf)

### Inferences
- `neighbor X description <text>` is very likely supported, but no source was found. Mark it unverified.
- The 4-byte ASN range was not checked. Validate ASNs as 1–4294967295 and test.

### Gaps
- The exact syntax and output of `show bgp ipv4 unicast summary` were not found in an official source.
- The `network` command was not confirmed on a 10.1x techdocs page.

## 9. Local users, SSH, HTTPS, enable secret

### Takeaway
`user <name> group administrators password plaintext <pw>` (config). The username must be lowercase, 32 characters at most, and not `admin`/`root`. SSH is `ssh server vrf {default|mgmt}`; HTTPS/Web UI is `https-server vrf {default|mgmt}`. **There is no enable secret.** A user lands in Manager (#) or Operator (>) according to their group. The plaintext password **appears in command history in cleartext**, so the push engine must mask it.

### Cited Findings
- Syntax: `user <USERNAME> group {administrators | operators | auditors | <USER-GROUP>} password [ciphertext <CIPHERTEXT-PASSWORD> | plaintext <PLAINTEXT-PASSWORD>]`, and `no user <USERNAME>`. Without ciphertext/plaintext the switch **prompts twice** for the password. Username rules: must start with a lowercase letter; may contain lowercase letters, digits, `-`, `.` and `_`; maximum 32 characters; no uppercase; cannot be `admin`, `root`, `remote_user` or Linux reserved names (daemon, bin, sys, sshd …). Up to 63 local users plus `admin`. The `admin` user cannot be deleted. — [C6100 p.1285](https://download.axilogi.com/HPE/Manual/HPE_6000_a_6100_MCG.pdf)
- The plaintext form "Specifies the password without prompting. The password is visible as cleartext when entered but is encrypted thereafter. Command history does show the password as cleartext." The running config shows `user X group administrators password ciphertext AQBap...`, and ciphertext only works between switches that share the same export password. — [C6100 p.1285–1286](https://download.axilogi.com/HPE/Manual/HPE_6000_a_6100_MCG.pdf); [F1010 p.196](https://www.bhphotovideo.com/lit_files/1146748.pdf)
- Security Guide example: `switch(config)# user TestUser1 group administrators password plaintext testuser1`. The capital letters in this example conflict with the lowercase-only rule in C6100. — search extract of [AOS-CX 10.14 Security Guide 6200/6300/6400 (mirror)](https://netz.schulon.org/fw/CX/Dokumentation/10.14/security_6200-6300-6400.pdf)
- `user <USERNAME> authorized-key <PUBKEY>` adds an SSH public key. Related global commands exist: `ssh password-authentication`, `ssh public-key-authentication`, `ssh maximum-auth-attempts`, `ssh ciphers`, `ssh macs`, `ssh key-exchange-algorithms` and `ssh host-key-algorithms`. — [C6100 TOC pp.1170–1182, 593](https://download.axilogi.com/HPE/Manual/HPE_6000_a_6100_MCG.pdf)
- `ssh server vrf <VRF-NAME>` / `no ssh server vrf <VRF-NAME>` (config). Examples: `ssh server vrf mgmt`, `no ssh server vrf mgmt`. The running config may contain both `ssh server vrf default` and `ssh server vrf mgmt`. — [C6100 p.1182](https://download.axilogi.com/HPE/Manual/HPE_6000_a_6100_MCG.pdf); [F1010 p.371](https://www.bhphotovideo.com/lit_files/1146748.pdf). The 6300/6400 10.16 Fundamentals says SSH is enabled on the mgmt VRF by default. — search extract of [techdocs 10.16 fundamentals 6300-6400 PDF](https://arubanetworking.hpe.com/techdocs/AOS-CX/10.16/PDF/fundamentals_6300-6400.pdf)
- `https-server vrf <VRF-NAME>` (config), e.g. `https-server vrf mgmt` and `https-server vrf default`. F1010 contradicts itself on the Web UI default: it says both "The Web UI is disabled by default" and "The Web UI is enabled by default on the default VRF". — [F1010 pp.30–31](https://www.bhphotovideo.com/lit_files/1146748.pdf); [C6100 p.372](https://download.axilogi.com/HPE/Manual/HPE_6000_a_6100_MCG.pdf)
- Built-in groups have fixed privileges, and "Users are given the privileges of their group". Operators can run `show running-config` only "from the operator context (>)". — [C6100 p.1285](https://download.axilogi.com/HPE/Manual/HPE_6000_a_6100_MCG.pdf); [F1010 p.127](https://www.bhphotovideo.com/lit_files/1146748.pdf)

### Inferences
- There is no `enable secret` equivalent in normal operation. An administrators-group login lands directly at `#`, so the push form's enable-secret field should be hidden or ignored for AOS-CX.
- Hardening generator: `no https-server vrf default` (and `mgmt` if not wanted), and `ssh server vrf <mgmt-vrf>`. **Management-interface protection** must block `no ssh server vrf <vrf>` for the VRF in use, and `no user <current-login>`.
- Masking: add `password plaintext`, `password ciphertext` and `authorized-key` to the mask patterns. Never send `user ... password plaintext` without masking it in job logs, because the device echoes it and keeps it in command history.

### Gaps
- No official statement was found that the SSH server is SSHv2-only, and no `ssh version` command appears. AOS-CX is generally SSHv2-only, but this is unverified here.
- Whether `password plaintext` accepts spaces or special characters (quoting rules) was not found.

## 10. Save, CLI error strings, verification commands

### Takeaway
Save with `write memory`, an alias of `copy running-config startup-config`; the output is `Success`. Documented error strings are `Invalid input: <token>` and `% Command incomplete.`. Verify with `show system`, `show version`, `show vlan`, `show interface [brief]`, `show ip interface <if>`, `show lldp neighbor-info detail`, `show ip ospf neighbors` and `show running-config`.

### Cited Findings
- `write memory` "Saves the running configuration to the startup configuration. It is an alias of the command copy running-config startup-config." Output: `Success`. Context Manager (#). — [F1010 p.203](https://www.bhphotovideo.com/lit_files/1146748.pdf)
- Error strings, exact: `Invalid input: 12` (the offending token is echoed after the colon) and `% Command incomplete.`. A semantic error example: `Prefix lengths must be specified in descending order`. — [F1010 pp.~22](https://www.bhphotovideo.com/lit_files/1146748.pdf) (ip prefix-priority examples). Also: "If the user tries to execute any command that is not allowed, an Invalid input: error message is displayed." — [F1010 Aruba Central support-mode section](https://www.bhphotovideo.com/lit_files/1146748.pdf)
- The REST "AnyCLI" error table groups "Invalid Input, Command incomplete or Ambiguous command" (HTTP 400, "Invalid command."), and other CLI failures as 502 "Command execution failed." — search extract of [techdocs 10.13 REST error codes](https://arubanetworking.hpe.com/techdocs/AOS-CX/10.13/HTML/rest_v10-0x/Content/Chp_AnyCLI/err-codes.htm)
- Full-text search of F1010 found 0 matches for "Unknown command" and "Ambiguous". — [F1010](https://www.bhphotovideo.com/lit_files/1146748.pdf)
- `show system` field labels (6300): `Hostname`, `System Description`, `System Contact`, `System Location`, `Vendor : Aruba`, `Product Name : JL659A 6300M 48SR5 CL6 PoE 4SFP56 Swch`, `Chassis Serial Nbr : ID9ZKHN090`, `Base MAC Address : 9020c2-245080`, `AOS-CX Version : FL.10.xx.xxxx`, `Time Zone`, `Up Time`, `CPU Util (%)`, `Memory Usage (%)`. — [F1010 p.374](https://www.bhphotovideo.com/lit_files/1146748.pdf)
- `show version` (6300) begins with a `ArubaOS-CX` banner, then `Version : FL.10.10.0001BJ`, `Build Date`, `Build ID`, `Build SHA`, `Hot Patches`, `Active Image : primary`, `Service OS Version`, `BIOS Version`. The `FL.` prefix is 6300/6400; the Simulator shows `Virtual.10.xx` (from the running-config header `!Version AOS-CX Virtual.10.0X.0001`). — [F1010 pp.264, 380–381](https://www.bhphotovideo.com/lit_files/1146748.pdf)
- `show interface [<IFNAME>|<IFRANGE>] [brief | physical | extended ...]` and `show interface [lag|loopback|tunnel|vlan] [<ID>] [brief|physical]`. Per-interface output starts `Interface 1/1/1 is up` / ` Admin state is up` / ` Link state: up for ...` / ` Description: ...`. — [F1010 pp.86–87](https://www.bhphotovideo.com/lit_files/1146748.pdf)
- `show ip interface <INTERFACE-ID> [vsx-peer]` is documented in F1010. **`show ip interface brief` does not appear** in F1010 (0 matches). — [F1010 p.~95](https://www.bhphotovideo.com/lit_files/1146748.pdf)
- `show lldp neighbor-info [<INTERFACE-NAME>]`, `show lldp neighbor-info detail` and `show lldp neighbor-info mgmt`. Detail output per port: `Port : 1/1/1`, `Neighbor Chassis-Name : 6300`, `Neighbor Chassis-Description`, `Neighbor Chassis-ID : 38:11:17:1a:d5:00`, `Neighbor Management-Address`, `Chassis Capabilities Available : Bridge, Router`, `Neighbor Port-ID : 1/1/4`, `Neighbor Port-Desc`, `Neighbor Port VLAN ID`, `TTL : 120`. — [F1010 pp.304–307](https://www.bhphotovideo.com/lit_files/1146748.pdf)
- `show running-config` starts `Current configuration:` / `!` / `!Version AOS-CX <ver>` / `!export-password: default`, with child lines indented under each context. — [F1010 p.264](https://www.bhphotovideo.com/lit_files/1146748.pdf). `show startup-config [json]` shows the startup config; factory-default switches have none. — [F1010 p.371](https://www.bhphotovideo.com/lit_files/1146748.pdf)
- `show capacities <FEATURE>` (e.g. `vlan-count`, `svi-count`) and `show capacities-status <FEATURE>` exist on 6000/6100 and give platform limits. — [C6100 pp.111–114, 1300–1302](https://download.axilogi.com/HPE/Manual/HPE_6000_a_6100_MCG.pdf)

### Inferences
- Driver `error_patterns()`: `^Invalid input:`, `% Command incomplete`, `Ambiguous command`, `% Unknown command`, `Prefix lengths must`, `Error:`, `% `. Lines starting with `% ` are errors; banner and checkpoint prompts are not. Test each one on the Simulator.
- For `management_interface()`, use `show ip interface <if>` per candidate interface, or parse `show running-config` for `ip address`/`ip static` lines, because `show ip interface brief` is unverified.
- Model and serial detection: parse `Product Name` and `Chassis Serial Nbr` from `show system`, and `Version` from `show version`. No `show inventory` page was found; `show module`/`show environment` were not checked.
- Denylist additions for AOS-CX: `erase startup-config`, `erase checkpoint`, `erase all`, `boot system`, `checkpoint rollback` from custom commands (only the engine may roll back), `no user`, `no ssh server vrf <mgmt-vrf>`, `zeroize` (not checked for AOS-CX), and `no interface vlan <mgmt-vlan>`.

### Gaps
- The exact strings for ambiguous and unknown commands on the interactive CLI are not confirmed in official text. Capture them on the Simulator.
- The `show interface brief` table header and `show bgp ipv4 unicast summary` output were not captured.
- `show ip interface brief` existence on 10.13–10.15 is unverified.
- `show inventory` was not found.
