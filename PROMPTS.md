
NetConfig Studio – build in 5 phases with Claude Code (VS Code)
Setup in VS Code (once)
Install VS Code, Python 3.12 (python.org – tick "Add to PATH"), Node.js LTS, Git, and MongoDB Community Server (as a Windows service).
VS Code → Extensions → install the official Claude Code extension (Anthropic) → sign in.
Copy the netconfig-studio folder (with CLAUDE.md, PROMPTS.md, frontend/) to your projects drive, e.g. D:\POJECTS\netconfig-studio. Delete frontend\node_modules and backend\.venv if present.
File → Open Folder → netconfig-studio, then open Claude Code.
Type / in Claude Code to see which skills and commands you have. Skills from plugins (names like engineering:... or design:...) need that plugin installed – use /plugin to browse and install. If a skill is not available, Claude Code can still do the step without it.
Paste one phase at a time. Each phase is split into parts (A, B, C…): paste a part, review the plan, let it build and test, commit, then paste the next part.
git add .
git commit -m "Phase 1A: backend skeleton"
Start a new Claude Code conversation for each phase. CLAUDE.md keeps the project context.
Skills used in this project
Skill / command	What it does for this project	Phase
engineering:architecture	Architecture decision records (driver design, local-app model)	1
engineering:system-design	Design of the backend, job runner and data model	1
archify	Architecture, push-flow and data-flow diagrams (HTML/SVG)	1, 5
engineering:testing-strategy	Test plan: unit, golden-file, fake-device, security tests	1, 2
fewer-permission-prompts	Adds safe read-only commands to the allowlist so Claude asks less	1
deep-research	Researches official vendor CLI documentation for each driver	2, 4
engineering:debug	Structured debugging when a push or test fails	3
run	Launches the app and checks a change really works	3, 4
ui-ux-pro-max / frontend-design	Keeps the liquid-glass design consistent for new screens	4
design:design-critique	Reviews the dashboard design	4
design:accessibility-review	WCAG accessibility audit of the UI	4
design:ux-copy	Clear labels, errors, empty states and warnings	4
dataviz	Correct, accessible charts on the Overview page	4
claude-api	Only if you choose Claude as the AI provider in phase 5	5
engineering:documentation	README, user guide, driver docs	5
engineering:tech-debt	Finds and ranks clean-up work before release	5
engineering:deploy-checklist	Release checklist	5
docx / pptx / pdf	Project report, viva presentation, PDF export	5
/code-review	Bug review of each part's changes	every phase
/simplify	Cleans up code after each phase	every phase
/security-review	Security review of the branch	every phase
Skills that are not used because they do not fit this project: Twilio, PlanetScale, Vanta, Cloudflare, Apple/iOS, Google Workspace, xlsx and the plugin-authoring skills.

PHASE 1 – Foundation: architecture, security, catalog and inventory
1A – Architecture and test plan
Read CLAUDE.md fully. We are starting Phase 1 of 5.

1. Use the engineering:system-design skill to design the backend: modules, MongoDB collections and
   indexes, the push-job lifecycle and state machine, and the API surface. Follow the architecture in
   CLAUDE.md section 2 – do not change it without asking.
2. Use the engineering:architecture skill to write ADRs in docs/adr/ for: (a) local app bound to
   127.0.0.1 instead of a cloud app, (b) OS-driver plugin design instead of per-model code,
   (c) Netmiko instead of automating PuTTY, (d) credentials in memory only.
3. Use the archify skill to create docs/diagrams/architecture.html and docs/diagrams/push-flow.html
   (validate → preview → approval → connect → backup → checks → apply → verify → save/rollback).
4. Use the engineering:testing-strategy skill to write docs/TEST_PLAN.md covering unit tests,
   golden-file tests per driver, fake-Netmiko push tests, security tests and manual lab tests.

Do not write application code in this part. Show me the plan first.
1B – Backend skeleton and security foundation
Read CLAUDE.md sections 3, 4, 8.1, 8.2 and 8.6 and the ADRs in docs/adr/. Phase 1B.

1. Initialise git and .gitignore. Create the backend skeleton from CLAUDE.md section 4 with pinned
   requirements (fastapi, uvicorn[standard], pydantic, pydantic-settings, pymongo, netmiko, pyserial,
   bcrypt, pytest, httpx, ruff, bandit, pip-audit) and .env.example with placeholders only.
2. /api/health (version + MongoDB status). Serve frontend/dist when present. Bind to 127.0.0.1.
   scripts/dev-backend.ps1 creates .venv with py -3.12, installs and runs uvicorn --reload.
3. Localhost guard: Host allowlist, Origin check + required X-Requested-With: NetConfigStudio on
   state-changing requests, strict security headers and CSP, safe errors with request IDs,
   /docs disabled when ENV=production.
4. Users (admin/engineer/viewer), bcrypt, password policy, lockout, server-side sessions with
   httpOnly SameSite=Strict cookies and TTL, logout, RBAC dependency on every route (deny by default),
   scripts/create_user.py with getpass, audit log service and /api/audit (admin).
5. Frontend: login page in the existing glass design, 401 handling, user menu + logout, API client
   that sends the custom header. No tokens in localStorage.
6. All security tests from CLAUDE.md section 9 for this part.

Finish by explaining simply why a local app needs Host/Origin checks (DNS rebinding, CSRF to localhost).
1C – Catalog and device inventory
Read CLAUDE.md sections 6 and 7. Phase 1C.

1. Move the sample catalog from frontend/src/data/catalog.js to backend/app/data/catalog.json
   (brands → series → models; OS drivers with support level, connections, apply mode, save command,
   netmiko device_type, capability matrix). scripts/seed_catalog.py seeds MongoDB. Mark specs
   "unverified sample data".
2. Optional scripts/import_netbox_devicetypes.py that imports models from a LOCAL clone of the NetBox
   community device-type library (document its licence; no automatic downloads).
3. API: catalog endpoints and device inventory CRUD (engineer+ create/edit, admin delete), strict
   validation, a "production" tag, never any passwords.
4. Frontend: Catalog, Devices and the wizard's device step use the API. Add an "Add device" form.
5. Tests for validation, RBAC and catalog queries.
1D – Phase 1 review
Phase 1 review.
1. Run /code-review on the Phase 1 changes and fix confirmed bugs.
2. Run /simplify.
3. Run /security-review and fix every finding that breaks CLAUDE.md section 8.
4. Use the fewer-permission-prompts skill to allowlist the safe read-only commands this project uses.
5. Run all tests and the app. Update README.md. Summarise what was built and what is not done.
PHASE 2 – Configuration engine: plans, validation and the Cisco IOS driver
2A – Research the Cisco IOS commands
Read CLAUDE.md sections 6 and 7. Phase 2 of 5.

Use the deep-research skill to research official Cisco documentation (IOS / IOS-XE configuration
guides and command references) for: VLANs, access ports, interface ranges, PortFast, port security,
trunks (allowed/native VLAN, dot1q encapsulation on L3 switches), SVIs and ip routing, routed
interfaces, DHCP pools and excluded addresses, NAT overload with ACLs, static routes, OSPF, EIGRP,
BGP, SSH v2 setup (RSA keys, VTY transport), hardening (service password-encryption,
login block-for, no ip http server, banners), archive + "configure terminal revert timer" +
"configure confirm", and common CLI error messages.

Write the result to docs/drivers/cisco_ios.md with exact command syntax, the verification show
commands and what their output looks like, and a source link for every item. No code yet.
2B – ConfigPlan, validation and the Cisco IOS driver
Read CLAUDE.md sections 6, 7 and 8.4, docs/drivers/cisco_ios.md and docs/TEST_PLAN.md. Phase 2B.

1. Pydantic ConfigPlan (basic, ssh, hardening, vlans, access, trunks, svis, interfaces, dhcp, nat,
   statics, routing, save) with limits and allowlisted characters (no newlines, "#", "^C", "|", ";").
2. services/validation.py with every check in section 8.4, errors keyed by field path ("vlans.0.id").
3. drivers/base.py interface + registry; drivers/cisco_ios.py implementing generate,
   verify_commands, check, error_patterns, save_command, rollback_strategy and management_interface,
   strictly following docs/drivers/cisco_ios.md. Secrets masked in previews.
4. POST /api/plans/preview → { errors } or { commands (masked), warnings, unsupported }.
5. Golden-file tests for every feature (tests/golden/cisco_ios/) and validation tests.
6. Frontend: Requirements and Preview steps use the API; the local preview stays only as an offline
   fallback.
2C – Phase 2 review
Phase 2 review: run /code-review and fix confirmed bugs, run /simplify, run /security-review
(focus: CLI command injection through hostnames, descriptions and banners). Run all tests and the
app, update README.md and summarise.
PHASE 3 – Safe push engine, first-time setup and multi-device features
3A – Push engine and jobs
Read CLAUDE.md sections 8.3 and 8.5 carefully. Phase 3 of 5.

1. services/push.py with Netmiko: SSH; serial console via pyserial; lab console via telnet only to
   loopback/RFC1918; enable mode; backup running config; pre-checks (denylist, management-interface
   protection); apply with error-pattern detection (stop at the first error and report the command);
   verification; save; rollback (Cisco archive + revert timer + configure confirm; restore backup
   otherwise). Handle the RSA "replace? [yes/no]" prompt safely.
2. SSH host-key fingerprint pinning (store on first connect, refuse on change unless an admin accepts).
3. services/jobs.py: background jobs with progress states, SecretStr credentials in memory only and
   wiped at the end, masked outputs saved to MongoDB.
4. API: POST /api/jobs, GET /api/jobs/{id} (progress), GET /api/jobs (history). Two-person approval
   for devices tagged production.
5. Tests with a FAKE Netmiko connection: success, CLI error mid-way, unreachable after apply →
   rollback, denylisted command blocked, management interface protected, secrets never stored.
6. Frontend: Push & verify shows live progress; History uses real jobs with commands, output and checks.
7. Use the run skill to start the backend and frontend and confirm a simulated push works end to end.
3B – Console bootstrap, router link wizard, multi-device push, templates
Read CLAUDE.md. Phase 3B.

1. Bootstrap over serial console (COMx) or lab console: handle the initial configuration dialog,
   then set hostname, management IP, default gateway, domain, admin user, enable secret, RSA keys,
   SSH v2 and VTY ssh-only. Test an SSH login, then switch the device's connection method to SSH.
2. Router link wizard: pick Router A and B interfaces and a /30 or /31; assign both IPs and matching
   OSPF area / EIGRP AS / BGP neighbours on both sides; validate both sides match; push as one job
   with two steps.
3. Multi-device push of the same VLAN set to several switches.
4. Saved templates that pre-fill the wizard.
5. docs/LAB_TESTING.md: step-by-step testing on Cisco IOSv/IOSvL2 in GNS3 or CML-Free.
6. Tests with the fake connection for every feature.
3C – Phase 3 review
Phase 3 review. If any test or push fails, use the engineering:debug skill to find the root cause
before fixing. Then run /code-review, /simplify and /security-review (focus: credential handling,
rollback paths, telnet/serial restrictions, host-key pinning). Run all tests and the app with the
run skill, update README.md and summarise.
PHASE 4 – Multi-vendor drivers, live dashboard and UI polish
4A – Research and build the Arista, Juniper and Aruba drivers
Read CLAUDE.md section 7. Phase 4 of 5.

1. Use the deep-research skill to research official documentation for Arista EOS, Juniper Junos
   (EX/SRX, ELS syntax) and HPE Aruba AOS-CX for the same feature list as docs/drivers/cisco_ios.md,
   including Junos "configure private", "commit check", "commit confirmed", interface-range and IRB,
   and AOS-CX vlan access / vlan trunk native / vlan trunk allowed. Write docs/drivers/<os>.md with
   sources.
2. Implement drivers/arista_eos.py, juniper_junos.py and aruba_aoscx.py with golden-file tests,
   capability matrices, error patterns and rollback strategies. Unsupported features (e.g. EIGRP on
   Junos) return clear errors.
3. Experimental drivers (disabled unless ENABLE_EXPERIMENTAL_DRIVERS=true): MikroTik RouterOS,
   Huawei VRP, D-Link, TP-Link – VLANs, access/trunk ports, hostname, SSH – each with documented sources.
4. Access points: show "managed by controller" and configure only the switch port they connect to.
   Cameras: read-only ONVIF information. Hubs/unmanaged: inventory only.
5. Update docs/LAB_TESTING.md for vJunos, cEOS-lab and the AOS-CX simulator. Keep new drivers
   "experimental" until I confirm lab tests passed.
4B – Live Overview dashboard
Read CLAUDE.md. Phase 4B: replace the Overview demo data with real data.

1. Status polling (ping + SSH reachability; optional read-only SNMPv3 sysName/sysDescr/sysObjectID)
   with a background scheduler in the local app.
2. Model/OS auto-detection from sysObjectID or "show version"; warn when it does not match the
   catalog model the user chose.
3. Topology from LLDP/CDP neighbour tables through the drivers, feeding the existing TopologyMap;
   VLAN tables from "show vlan brief" (or the driver equivalent).
4. KPIs and charts from real jobs and device status. Use the dataviz skill for the charts
   (accessible colours, legends, tooltips, light and dark theme).
5. Loading skeletons and empty states in the existing glass design.
4C – UI/UX polish and accessibility
Phase 4C: UI quality pass. Keep the existing liquid-glass design system in
frontend/src/styles/tokens.css and app.css.

1. Use the ui-ux-pro-max skill (or frontend-design if unavailable) to check every page against its
   rules: glass consistency, spacing scale, typography, 44 px touch targets, motion and
   reduced-motion, mobile layout at 375 px with no horizontal page scroll.
2. Use the design:design-critique skill on Overview, Configure and History and apply the agreed
   improvements.
3. Use the design:accessibility-review skill (WCAG 2.1 AA): contrast in both themes, keyboard
   navigation of the topology map and wizard, focus management between wizard steps, screen-reader
   labels. Fix all issues.
4. Use the design:ux-copy skill for labels, validation errors, safety warnings (production devices,
   telnet/console, rollback) and empty states.
5. Use the run skill to check every page in light and dark mode on desktop and phone width.
4D – Phase 4 review
Phase 4 review: run /code-review, /simplify and /security-review. Run all tests and the app,
update README.md and docs/drivers/, and summarise which drivers are tested vs experimental.
PHASE 5 – AI assistant, hardening, documentation and release
5A – AI assistant (optional, free)
Read CLAUDE.md. Phase 5 of 5.

1. "Describe what you need" box in the wizard: the engineer types e.g. "3 departments with 40 users
   each, Wi-Fi on VLAN 30, OSPF to the core". An LLM returns a ConfigPlan JSON draft. Provider and
   key come from .env: Ollama locally (free) or the Gemini/Groq free tier. If I choose Claude as the
   provider, use the claude-api skill for the correct model ID and SDK usage.
2. The draft goes through the same validation, preview, safety checks and approval as a manual plan.
   AI output is never pushed directly.
3. "Explain" buttons for a command block, a verification failure, or a config diff.
4. Never send device credentials, secrets or unmasked configs to the LLM. Treat device output as
   untrusted input (prompt injection). Add tests for this.
5B – Full security hardening
Act as a security reviewer of the whole project.
1. Check every rule in CLAUDE.md section 8 and report PASS / FAIL / PARTIAL with file and line.
   Fix every FAIL and PARTIAL.
2. Run /security-review on the whole branch and fix findings.
3. Run bandit, pip-audit, npm audit and ruff; fix or document accepted risks.
4. Confirm every API route has authentication and RBAC tests.
5. Write docs/SECURITY.md (STRIDE threat model: browser, local API, device connections, database,
   AI provider; controls; limitations) and docs/SECURITY_TESTING.md (how I demo Host/Origin
   protection, lockout, RBAC, the denylist, management-interface protection, host-key pinning and
   rollback in an interview).
5C – Clean-up, documentation and release
1. Use the engineering:tech-debt skill to list remaining tech debt; fix the high-priority items.
2. Run /code-review on the whole project and /simplify.
3. Use the engineering:documentation skill to finish README.md, docs/USER_GUIDE.md and
   docs/DRIVERS.md (how to add a new vendor driver).
4. Use the archify skill to update the architecture and push-flow diagrams to match the final code.
5. Production build: FastAPI serves frontend/dist; scripts/start.ps1 starts everything on Windows.
6. Use the engineering:deploy-checklist skill to produce docs/RELEASE_CHECKLIST.md and go through it.
7. Use the run skill for a final end-to-end check against the lab or the fake device.
5D – Project report and viva presentation
1. Use the docx skill to write docs/NetConfig_Studio_Report.docx: abstract, problem statement,
   literature review (manual CLI/PuTTY, Ansible, Cisco Catalyst Center, NetBox, vendor tools) and the
   gap, objectives, architecture (include the archify diagrams as images), driver design, security
   design, AI design, testing results, screenshots, limitations, future work, references.
2. Use the pptx skill to create docs/NetConfig_Studio_Viva.pptx (12–15 slides) for my project
   presentation, with a 5-minute live demo script in the speaker notes.
3. Use the pdf skill to export the report to PDF for submission.
Useful prompts at any time
Bug fix

Use the engineering:debug skill. Bug: <what I did> → <what I expected> → <what happened>.
Error: <paste>. Find the root cause, explain it, fix it, and add a test that would have caught it.
Explain for interviews

Explain how <feature> works in this project as if I am answering an interviewer: the problem,
the design, the security decisions, and one limitation. Under 2 minutes of speaking.
