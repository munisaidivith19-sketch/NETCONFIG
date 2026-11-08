# ADR-0002: One driver per OS family instead of per-model code

**Status:** Accepted (2026-11-08)
**Date:** 2026-11-08
**Deciders:** Project author

## Context
The catalog will hold hundreds or thousands of models (more after the optional NetBox import). But the
*commands* to create a VLAN or a trunk depend on the **operating system** (Cisco IOS, Arista EOS, Junos,
AOS-CX…), not on the model. A Catalyst 9200 and a Catalyst 9300 take the same `switchport mode access`.
What changes between models is data: port count, port naming (`GigabitEthernet1/0/x` vs `ge-0/0/x`),
PoE, Layer 2 or Layer 3.

## Decision
- **Models are catalog data** that point to an `os_id`, with port naming patterns and capability overrides.
- **One driver per OS family** implements the `Driver` protocol (`CLAUDE.md` section 7): `generate`,
  `verify_commands`, `check`, `error_patterns`, `save_command`, `rollback_strategy`, `management_interface`.
- Drivers are **pure functions** with no device or database access, so they are tested with golden files
  (`tests/golden/<os_id>/<case>.txt`).
- A `registry` maps `os_id → driver`. Experimental drivers load only when `ENABLE_EXPERIMENTAL_DRIVERS=true`.
- An unsupported feature raises a clear "not supported on <OS>" error. Nothing is ever skipped silently.
- Effective capabilities = driver capabilities ∩ model capabilities (an L2-only model gets no SVI or OSPF).

## Options Considered

### Option A: OS-driver plugins (chosen)
| Dimension | Assessment |
|-----------|------------|
| Complexity | Medium – one clear interface |
| Cost | Free |
| Scalability | New model = a data row; new vendor = one driver file + golden tests |
| Team familiarity | High |

**Pros:** small code size; each vendor is researched once; golden tests per OS; adding models needs no code.
**Cons:** the per-OS abstraction must handle real differences (Junos commit model, AOS-CX `vlan trunk` syntax);
model quirks need a capability-override mechanism.

### Option B: Per-model templates (e.g. one Jinja file per model)
**Pros:** each file is simple. **Cons:** huge duplication; a bug fix has to be made in hundreds of files;
untestable at scale; the catalog import would require code changes.

### Option C: Use an existing abstraction (NAPALM / Nornir templates)
**Pros:** mature getters. **Cons:** NAPALM config is "merge a text blob", so we would still write the
generators; it adds a major dependency and needs approval under `CLAUDE.md` section 10. It could be added
later for getters (LLDP, facts) only.

## Trade-off Analysis
Option A puts vendor knowledge in exactly one place per OS and keeps it pure, which is what makes
golden-file testing and command-injection review practical. The cost is designing a good interface up
front. That is acceptable because section 7 already defines it.

## Consequences
- Easier: adding models and vendors, testing, reviewing generated commands.
- Harder: OS versions that differ slightly (IOS vs IOS-XE) must be handled inside one driver with flags.
- Revisit: split a driver (e.g. `cisco_iosxe`) if version differences grow.

## Action Items
1. [ ] `drivers/base.py` (Protocol, `Check`, `UnsupportedFeature`) and `registry.py` (Phase 2B).
2. [ ] `catalog.json` uses `os_id`, `port_pattern` and `capabilities_override` per model (Phase 1C).
3. [ ] Golden-file test harness that runs every case per driver.
4. [ ] `docs/DRIVERS.md`: how to add a new vendor (Phase 5C).
