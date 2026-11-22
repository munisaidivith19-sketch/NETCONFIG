# Adding a vendor driver

How to teach NetConfig Studio a new network OS. The status of the existing drivers is in
[`docs/drivers/README.md`](drivers/README.md); the design decision is [ADR-0002](adr/0002-os-driver-plugin-design.md).

## 1. The idea in one paragraph

Commands depend on the **OS family, not the model**. A driver is one Python class per OS that turns a
validated `ConfigPlan` into that OS's CLI commands, plus the `show` commands and checks that prove the
change worked. Generators are **pure functions**: no device access, so they are tested with golden files.
Everything that touches a device (connect, backup, apply, rollback) lives in the push engine
(`services/push.py`), which asks the driver *which* commands to send but contains no vendor command itself.
Models in `catalog.json` point to a driver through `os_id`.

```
ConfigPlan ──► validation.py ──► driver.review() ──► driver.generate() ──► safety.py ──► preview / job
 (form)        (generic rules)    (OS-specific rules)   (commands)        (denylist,
                                                                           management port)
job run ──► push.py: connect ─ backup ─ driver.precheck_commands ─ driver.session(): begin/apply/check/arm
                     ─ error_patterns ─ driver.verify_commands + driver.check() ─ confirm ─ save_command
```

## 2. Before writing code

1. **Find the vendor documentation** for every command you will generate, and write it down in
   `docs/drivers/<os_id>.md` with links (CLAUDE.md §10: never invent a command). Mark every line you could not
   check on a device with **[LAB]**.
2. **Check Netmiko** has a `device_type` for the OS (`netmiko.platforms`). Without it, the driver cannot connect.
3. **Decide the rollback strategy** (section 5). This decides whether the driver can be more than experimental.
4. **Decide which capabilities** you will implement: `vlans, access, trunk, svi, routed_if, dhcp, nat, static,
   ospf, eigrp, bgp, ssh` (and `default_gateway` for Layer 2 switches). Start small. Anything you leave out is
   refused with "<feature> is not supported on <OS>", never silently skipped.

## 3. Files to add or change

| File | What |
|---|---|
| `backend/app/drivers/<os_id>.py` (or `drivers/experimental/<os_id>.py`) | The driver class |
| `backend/app/drivers/registry.py` | Add it to `CORE` (always loaded) or `EXPERIMENTAL` (only with `ENABLE_EXPERIMENTAL_DRIVERS=true`) |
| `backend/app/data/catalog.json` | An `os_drivers` entry, a brand, at least one series and one model (section 6) |
| `backend/app/services/discovery.py` | A line in `OS_SIGNATURES` so "Read device facts" warns when a device runs a different OS |
| `backend/app/security/masking.py` | Only if the OS writes secrets in a form the existing patterns miss (test it) |
| `backend/app/services/safety.py` | Only if the OS's CLI is not IOS-style or Junos `set` style: a `check_management_<syntax>()` for the management-port rules (see RouterOS and D-Link) |
| `backend/tests/golden/<os_id>/*.json, *.txt, *.verify.txt` | Golden cases (section 7) |
| `backend/tests/drivers/` | Unit tests for review rules, parsers, denylist, management interface |
| `docs/drivers/<os_id>.md` | Command reference with sources and **[LAB]** marks |
| `docs/LAB_TESTING.md` | The checklist that will make the driver `tested` |

## 4. The driver class

The full interface is the `Driver` protocol in `backend/app/drivers/base.py`. Inherit `DriverDefaults`
(`drivers/common.py`), which gives the "not supported on <OS>" check and push hooks that do nothing; the four
experimental drivers inherit `ExperimentalDriver` (`drivers/experimental/base.py`), the smallest complete
example to copy.

**Identity**

| Attribute | Example (TP-Link) | Meaning |
|---|---|---|
| `os_id` | `"tplink_jetstream"` | Must match the catalog `os_drivers._id` |
| `os_name` | `"TP-Link JetStream"` | Shown in messages: "port security is not supported by the TP-Link JetStream driver" |
| `netmiko_device_type` | `"tplink_jetstream"` | `_telnet` / `_serial` are appended for lab consoles and console cables |
| `capabilities` | `{"vlans", "access", "trunk", "ssh"}` | What `generate()` can do |
| `cli_syntax` | `"ios"` | Picks the management-port rules in `safety.py`: `ios`, `set`, `routeros`, `dlink` |
| `config_prompt` | `r"\(config[^)]*\)#"` | Regex of the config-mode prompt |

**Generating** (pure, no device access)

- `review(plan) -> (errors_by_field, warnings)`: OS-specific rules, e.g. "TP-Link host names have at most 32
  characters". Errors are keyed by the plan field (`"basic.hostname"`), so the form highlights the right box.
- `generate(plan, kind) -> list[str]`: call `self._check_features(plan)` first. `kind` is `"preview"` or
  `"push"`: secrets are only filled in for `"push"` (use `secret_value()` from `drivers/common.py`), the
  preview shows them masked.
- `normalize_interface(name)`: `"gi1/0/1"` → the catalog's spelling, so validation and the management-port
  check compare like with like (`normalize_by_types()` helps).
- `verify_commands(plan)` and `check(plan, outputs) -> list[Check]`: the `show` commands after applying, and
  the checks on their output. `Check(required=False)` for things that take time (a BGP session coming up).

**Safety**

- `denylist()`: extra denied commands for this OS, as `((keywords...), label)`; matched on whole commands
  with abbreviations (`services/safety.py`). Always deny: commands that commit, roll back or leave the
  config session (only the engine does that), shells, reboots, and **features that store a command and run
  it later** (Cisco `event manager`, EOS `event-handler`/`schedule`, RouterOS `system scheduler`,
  Junos `set event-options`): the stored command would not start with the denied word.
- `error_patterns()` / `info_patterns()`: CLI output that stops the push at that command
  (`% Invalid input`, `syntax error`, …), and lines that look like errors but are not.
- `management_commands()` and `management_interface(outputs, mgmt_ip)`: how to find the interface that holds
  the address the app is connected to, so plans that would cut that connection are blocked.

**Push hooks**

- `session(plan, name) -> Session`: the commands that enter config mode, start the safety timer, check,
  commit, confirm, revert or discard (section 5).
- `backup_command()`, `save_command()`, `rollback_strategy()`.
- Optional: `precheck_commands()` + `adapt_commands()` (read the device first, e.g. Cisco checks
  `show ip ssh` before generating RSA keys), `prompts()` (questions the CLI asks, with the answer),
  `rollback_setup()` (config the rollback needs, e.g. the Cisco `archive`).
- Discovery (read only): `facts_commands()/parse_facts()`, `neighbor_commands()/parse_neighbors()`,
  `vlan_commands()/parse_vlans()`. Return `[]` to skip.

## 5. Rollback: what makes a driver safe

| Strategy | How | Drivers |
|---|---|---|
| `revert_timer` | The change runs under a device-side timer; `configure confirm` after verification | Cisco IOS |
| `commit_confirmed` | `commit confirmed N`, then `commit` | Junos |
| `session_timer` | `configure session` → `commit timer` → commit the session | Arista EOS |
| `checkpoint` | `checkpoint auto N` → `checkpoint auto confirm` | Aruba AOS-CX |
| `backup_restore` | No timer: on failure a person restores the backup saved with the job | experimental drivers |

A device-side timer matters because it still works when the laptop loses the connection: the device rolls
itself back. A driver with only `backup_restore` stays experimental, and production devices cannot use it
unless `ENABLE_EXPERIMENTAL_DRIVERS=true`.

## 6. Catalog entries

```jsonc
// os_drivers
{"_id": "tplink_jetstream", "name": "TP-Link JetStream", "vendor": "TP-Link", "support": "experimental",
 "connections": ["ssh"], "apply_mode": "immediate",
 "save_command": "copy running-config startup-config", "netmiko_device_type": "tplink_jetstream",
 "rollback": "backup_restore", "capabilities": ["vlans", "access", "trunk", "ssh"], "note": "..."}
// models: port_pattern is what interface names are validated against (CLAUDE.md 8.4)
{"_id": "tplink-tl-sg2210p", "series_id": "tplink-jetstream", "brand_id": "tplink", "name": "TL-SG2210P",
 "category": "switch", "os_id": "tplink_jetstream", "layer": 2, "ports": 10, "uplinks": 2, "poe": true,
 "port_prefix": "gigabitEthernet", "port_pattern": "^gigabitEthernet1/0/(?:1|2|3|4|5|6|7|8|9|10)$",
 "port_examples": ["gigabitEthernet1/0/1", "gigabitEthernet1/0/10"], "capabilities_exclude": [],
 "source": "sample", "verified": false, "driver_flags": {}}
```

New drivers always start with `"support": "experimental"` and sample models with `"verified": false`. Load the
changes with `.venv\Scripts\python scripts\seed_catalog.py` (the app seeds the catalog on start only when it is
empty).

## 7. Tests

**Golden files** (`tests/drivers/test_golden.py` finds them automatically):

```
tests/golden/<os_id>/vlans_access_trunk.json        {"model_id": "...", "plan": {...}}
tests/golden/<os_id>/vlans_access_trunk.txt         the exact commands generate() must return
tests/golden/<os_id>/vlans_access_trunk.verify.txt  the exact verify commands
tests/golden/<os_id>/ospf_unsupported.json          {"model_id": "...", "plan": {...},
                                                     "expect_errors": {"routing.ospf": "not supported"}}
```

Write the `.json` cases, run `UPDATE_GOLDEN=1 .venv\Scripts\python -m pytest tests/drivers` to create the
`.txt` files, then **read every line against the vendor documentation**: that review is the point of golden
files. Every golden command list is also run through the denylist. A `CORE` driver must have all 16
`REQUIRED_CASES` (unsupported features as `expect_errors` cases).

**Unit tests** to add (copy from `tests/drivers/test_experimental_drivers.py` / `test_phase4_drivers.py`):
review rules, the denylist (`test_driver_denylist`), `management_interface()` on sample output, discovery
parsers on real `show` output, secrets present only for `kind="push"` and masked in job records.

**Push engine:** `tests/push/fake.py` is a fake Netmiko connection; add a case if the OS's session works
differently from the existing ones.

Then: `powershell -ExecutionPolicy Bypass -File scripts\check.ps1`.

## 8. From experimental to tested

1. Add the OS to `docs/LAB_TESTING.md` and run it on an emulator (or real hardware): every capability, a CLI
   error mid-way, a verification failure, loss of connection after applying, and the management-port block.
2. Fix every **[LAB]** item that behaved differently, and update the golden files.
3. Set `"support": "tested"` in `catalog.json`, update the table in `docs/drivers/README.md`, and record the
   date and image version there.
