# ADR-0001: Run as a local app bound to 127.0.0.1 instead of a cloud app

**Status:** Accepted (2026-11-08)
**Date:** 2026-11-08
**Deciders:** Project author

## Context
NetConfig Studio has to open SSH, serial-console and lab-telnet sessions to switches and routers. Those
devices sit on private management networks (RFC1918 addresses, out-of-band VLANs, console cables)
that the public internet cannot reach. The tool also handles the most sensitive data a network has:
device credentials and running configurations. The project must use free tools only and run natively
on Windows 11.

## Decision
Run the FastAPI backend **on the engineer's own laptop, inside the network**, bound to `127.0.0.1` by
default. The same process serves the built React frontend (same origin). Binding to any other address
requires `ALLOW_REMOTE=true`, HTTPS and login, and prints a warning at startup.

Because "localhost" is not a security boundary on its own, the app also enforces:
a **Host header allowlist** (against DNS rebinding), an **Origin check plus a required
`X-Requested-With: NetConfigStudio` header** on state-changing requests (against CSRF to localhost),
strict security headers/CSP, and authenticated sessions.

## Options Considered

### Option A: Local app on 127.0.0.1 (chosen)
| Dimension | Assessment |
|-----------|------------|
| Complexity | Low – one process, one local MongoDB |
| Cost | Free |
| Scalability | One engineer / small team; enough for the use case |
| Team familiarity | High (Python + React) |

**Pros:** reaches devices directly (including COM ports); credentials and configs never leave the
laptop; no internet-facing attack surface; works offline in a lab.
**Cons:** no shared central view across engineers; must defend against browser-based attacks on
localhost (DNS rebinding, CSRF); the laptop is a single point of failure.

### Option B: Cloud web app (e.g. Render / Atlas)
| Dimension | Assessment |
|-----------|------------|
| Complexity | High – needs an agent or VPN inside every site to reach devices |
| Cost | Free tiers are limited; agents add work |
| Scalability | High |
| Team familiarity | Medium |

**Pros:** multi-user and accessible anywhere.
**Cons:** cannot reach private management networks without an on-prem agent or VPN; credentials and
configs cross the internet and sit in a third-party cloud; serial console is impossible; a much larger
attack surface for a tool that can reconfigure the whole network.

### Option C: Self-hosted server inside the network
**Pros:** shared by a team. **Cons:** needs a server, TLS, hardening and patching. This is out of scope
for a student project but remains possible later through `ALLOW_REMOTE`.

## Trade-off Analysis
The deciding factor is **reachability plus trust**. A config tool must sit where the devices are, and
the safest place for credentials is a machine the engineer already controls. We accept the loss of a
central multi-user view and pay for it with explicit localhost hardening. "It's only on localhost"
is never treated as the security control itself.

## Consequences
- Easier: device access, serial console, data stays local, simple setup on Windows.
- Harder: every request must pass Host/Origin/custom-header checks; these need tests.
- Revisit: a team deployment (Option C) if multi-user need grows; this requires TLS and a review of ADR-0004.

## Action Items
1. [ ] `HOST=127.0.0.1` default in `config.py`; refuse other hosts unless `ALLOW_REMOTE=true`.
2. [ ] Implement HostAllowlist and OriginAndCustomHeader middleware (Phase 1B).
3. [ ] Security tests: wrong Host, cross-origin POST and missing custom header are all rejected.
4. [ ] Explain DNS rebinding and CSRF-to-localhost in `docs/SECURITY.md`.
