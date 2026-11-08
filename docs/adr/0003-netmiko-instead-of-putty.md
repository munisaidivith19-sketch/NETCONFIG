# ADR-0003: Use Netmiko instead of automating PuTTY

**Status:** Accepted (2026-11-08)
**Date:** 2026-11-08
**Deciders:** Project author

## Context
Engineers configure devices today by typing into PuTTY over SSH, Telnet or a serial cable. The tool
needs the same three transports, but driven by code. That code has to detect prompts (`>`, `#`,
`(config)#`), enter enable mode, spot CLI errors, and capture output for verification and audit.

## Decision
Use **Netmiko** (with **pyserial** for COM ports) as the only device-connection library, behind a
small `Connection` interface in `services/push.py` that tests replace with a `FakeConnection`.
PuTTY is not used or automated.

## Options Considered

### Option A: Netmiko (chosen)
| Dimension | Assessment |
|-----------|------------|
| Complexity | Low – `ConnectHandler(device_type=…)` |
| Cost | Free, MIT licence |
| Scalability | One session per thread; enough for ≤ 10 concurrent jobs |
| Team familiarity | High, widely taught |

**Pros:** supports `cisco_ios`, `arista_eos`, `juniper_junos`, `aruba_aoscx`, `*_telnet` and `*_serial`
device types; handles prompts, paging, enable and config mode; `send_config_set` returns output we can scan for errors.
**Cons:** synchronous (fine with threads); its session log must be disabled or masked (see ADR-0004).

### Option B: Automate PuTTY (`plink.exe` / SendKeys)
**Pros:** "uses the tool engineers know". **Cons:** screen scraping is fragile; plink takes passwords
on the command line, where other processes can see them; no reliable prompt or error detection;
Windows-only; cannot be unit-tested.

### Option C: Raw Paramiko / Scrapli
**Pros:** Paramiko is lower level; Scrapli is fast and async. **Cons:** with Paramiko we would rewrite
prompt handling per vendor. Scrapli is a reasonable alternative but is less common in teaching
material and its serial support is weaker.

## Trade-off Analysis
Netmiko gives the same transports as PuTTY with vendor-aware prompt handling, and nothing that is
hard to test. Automating PuTTY looks familiar but would make error detection, which is the core
safety feature, unreliable.

## Consequences
- Easier: one API for SSH, telnet-lab and serial; fake connections in tests.
- Harder: host-key handling must be done by us (Netmiko/Paramiko defaults are not pinning). See the Phase 3A host-key pinning work.
- Revisit: Scrapli if async or performance becomes important.

## Action Items
1. [ ] Pin the `netmiko` and `pyserial` versions in `requirements.txt` (Phase 1B).
2. [ ] `Connection` protocol + `FakeConnection` for tests (Phase 3A).
3. [ ] Disable Netmiko `session_log` or route it through masking.
4. [ ] Telnet only to loopback/RFC1918 lab consoles; serial only for bootstrap.
