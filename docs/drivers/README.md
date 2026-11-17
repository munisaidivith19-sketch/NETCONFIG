# OS drivers – status overview

Commands depend on the **OS family**, not the model. Each driver in `backend/app/drivers/` turns a validated
ConfigPlan into commands for one OS, and catalog models point to a driver through `os_id`. Status as of the
Phase 4 review (2026-11-15).

## Tested vs experimental

**No driver is `tested` yet.** A driver becomes `tested` only after its checklist in `docs/LAB_TESTING.md`
passes on an emulator. That lab work has not been run. Until then every driver below has golden-file unit
tests, but it is labelled *experimental* in the UI and every preview carries a warning.

| Driver (`os_id`) | Support | Enabled | Rollback | Features | Golden files | Lab target | Reference |
|---|---|---|---|---|---|---|---|
| Cisco IOS / IOS-XE (`cisco_ios`) | experimental | yes | `revert_timer`: `configure terminal revert timer N` → `configure confirm` | all 12 + default gateway | 52 | IOSv, IOSvL2 | [cisco_ios.md](cisco_ios.md) |
| Juniper Junos ELS (`juniper_junos`) | experimental | yes | `commit_confirmed`: `commit confirmed N` → `commit` | all except EIGRP | 52 | vJunos-switch / router (vSRX for NAT) | [juniper_junos.md](juniper_junos.md) |
| Arista EOS (`arista_eos`) | experimental | yes | `session_timer`: `configure session` → `commit timer hh:mm:ss` → `configure session <name> commit` | all except EIGRP | 49 | cEOS-lab | [arista_eos.md](arista_eos.md) |
| HPE Aruba AOS-CX (`aruba_aoscx`) | experimental | yes | `checkpoint`: `checkpoint auto N` → `checkpoint auto confirm` | all except NAT and EIGRP (the 6100 also has no OSPF, BGP or DHCP server) | 50 | AOS-CX Simulator | [aruba_aoscx.md](aruba_aoscx.md) |
| MikroTik RouterOS (`mikrotik_routeros`) | experimental | only with `ENABLE_EXPERIMENTAL_DRIVERS=true` | `backup_restore` (manual) | hostname, SSH, VLANs, access, trunk | 12 | MikroTik CHR | [experimental.md](experimental.md) |
| Huawei VRP (`huawei_vrp`) | experimental | only with the flag | `backup_restore` (manual) | same small set | 12 | – (no free emulator) | [experimental.md](experimental.md) |
| D-Link DGS (`dlink_ds`) | experimental | only with the flag | `backup_restore` (manual) | same small set | 10 | – | [experimental.md](experimental.md) |
| TP-Link JetStream (`tplink_jetstream`) | experimental | only with the flag | `backup_restore` (manual) | same small set | 12 | – | [experimental.md](experimental.md) |
| Controller-managed AP, IP camera, unmanaged | inventory | yes | – | none: inventory and status only, no config push | – | – | – |

"All 12" means the CLAUDE.md capability matrix: VLANs, access, trunk, SVI, routed interfaces, DHCP, NAT,
static routes, OSPF, EIGRP, BGP and SSH. A plan feature that a driver does not support is refused with
"<feature> is not supported on <OS>". It is never silently skipped.

## What "tested" will mean

1. Run the driver's part of `docs/LAB_TESTING.md` on the emulator listed above, and record the date and
   image version.
2. Fix any **[LAB]** item that behaves differently from the documentation.
3. Change `support` to `tested` for that OS in `backend/app/data/catalog.json` and update the table above.

Huawei, D-Link and TP-Link have no free emulator. They stay experimental unless real hardware is
available.

## Research notes

`research/` holds the full research notes and citations for each driver. Evidence levels (V/O/C/U) are
explained in each driver document.
