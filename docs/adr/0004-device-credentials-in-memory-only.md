# ADR-0004: Device credentials held in memory only, for one job

**Status:** Accepted (2026-11-08)
**Date:** 2026-11-08
**Deciders:** Project author

## Context
To push a config, the app needs a device username, password and often an enable secret. A stolen
credential store from a config tool would give an attacker the whole network. Credentials can leak
through many paths: the database, log files, job records, exception messages, Netmiko session logs,
and browser storage.

## Decision
- Credentials are entered **at push time** (`POST /api/jobs/{id}/run`) and parsed into Pydantic
  `SecretStr`, so `repr()`/logging shows `**********`.
- They go into an in-memory vault `{job_id: Credentials}` used only by the job thread, and they are
  **deleted in a `finally:` block** when the job reaches a terminal state, including on errors.
- They are **never** written to MongoDB, logs, job records, exceptions or the browser's storage. The
  frontend keeps them in component state only and clears them after submitting.
- For production devices, approval happens **before** credentials are supplied, so secrets are never
  held while waiting for a human (see `SYSTEM_DESIGN.md` §5.1).
- Netmiko session logging is disabled. Everything stored (commands, output, backups) goes through
  `security/masking.py` (`password`, `secret`, `community`, `key-string`, `encrypted-password`, `pre-shared-key`).
- Error messages passed to the user are sanitised (for example, a Netmiko auth exception becomes "authentication failed").

## Options Considered

### Option A: Memory only, per job (chosen)
| Dimension | Assessment |
|-----------|------------|
| Complexity | Low |
| Cost | Free |
| Usability | The engineer retypes credentials for each push |
| Security | Strongest. Nothing at rest to steal |

### Option B: Encrypted vault in MongoDB (key from env / DPAPI)
**Pros:** no retyping; allows scheduled jobs. **Cons:** the key sits on the same laptop as the data,
so a laptop compromise exposes every device credential; key rotation and backup add complexity.

### Option C: Windows Credential Manager / OS keyring
**Pros:** OS-protected. **Cons:** any process running as the user can read it; adds a dependency.
A reasonable future option behind an explicit opt-in.

## Trade-off Analysis
We trade convenience (retyping) for having nothing to steal at rest. For a tool used interactively
by an engineer, retyping is acceptable. Phase 4 status polling uses ping, SSH reachability and SNMPv3
read-only, so it does not need the config credentials. If SNMPv3 credentials are added, they need
their own decision.

## Limitations (honest)
Python cannot reliably zero memory: strings are immutable and may be copied, and Paramiko holds the
password while the session is open. "Wiped" means *all references are dropped and the vault entry is
deleted*. It does not mean the bytes are overwritten. A memory dump of the running process during a
job could still reveal the password. This goes in `docs/SECURITY.md`.

## Consequences
- Easier: no secret storage to protect, rotate or back up.
- Harder: scheduled/unattended pushes are impossible by design; every test must check that secrets never reach the database or logs.
- Revisit: OS keyring (Option C) as an opt-in if unattended jobs are ever needed.

## Action Items
1. [ ] `Credentials` model with `SecretStr`, and `extra="forbid"` (Phase 3A).
2. [ ] Vault with `try/finally` cleanup; test that the vault is empty after success, failure and exceptions.
3. [ ] Masking utility + tests for every secret keyword (Phase 1B).
4. [ ] Test: search every stored job/audit document and the log output for the test password, and expect no match.
