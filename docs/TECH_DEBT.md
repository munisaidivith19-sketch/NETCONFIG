# Tech debt register

Reviewed in Phase 5C (2026-11-22). Score = (Impact + Risk) × (6 − Effort), each rated 1–5 (Effort 1 = small).
Re-check this list at every release (`docs/RELEASE_CHECKLIST.md`).

| # | Item | Type | Impact | Risk | Effort | Score | Status |
|---|---|---|---|---|---|---|---|
| 1 | Release checks (tests, ruff, bandit, pip-audit, vitest, build, npm audit) had to be run one by one; easy to forget one, and pip-audit always "failed" on the accepted CVEs | Infrastructure | 3 | 3 | 1 | 30 | **Fixed:** `scripts\check.ps1` runs them all, makes database tests fail instead of skip (`REQUIRE_MONGO=1`, read in `tests/conftest.py`), and ignores only the CVE IDs listed in `docs/ACCEPTED_RISKS.md` (one list, read by the script) |
| 2 | Six pages had no test at all (History, Catalog, Account, Audit, Users, SSH host keys), including the host-key "accept new key" flow | Test | 3 | 3 | 2 | 24 | **Fixed:** `Pages.test.jsx` (each page renders behind sign-in) and `admin/HostKeys.test.jsx` (nothing is accepted before the fingerprint dialog is confirmed) |
| 3 | `.venv` runs Python 3.10, not the 3.12 target. Two accepted dependency findings (`dnspython`, `filelock`) can only be fixed on ≥ 3.11 | Dependency | 2 | 4 | 2 | 24 | **Needs the author:** install Python 3.12 from python.org, delete `backend\.venv`, run `scripts\dev-backend.ps1`, upgrade the two packages, remove the rows in `ACCEPTED_RISKS.md` (`check.ps1` reads its IDs from there) |
| 4 | Starlette deprecates `httpx` in its test client (`install httpx2 instead`). Tests still pass; a future Starlette upgrade will break them | Dependency / test | 2 | 3 | 1 | 25 | **Needs approval:** swapping the pinned dev dependency `httpx` for `httpx2` is a new library (CLAUDE.md §10) |
| 5 | No driver is marked `tested`: none has been run on an emulator yet | Test | 5 | 5 | 4 | 20 | **Needs the lab:** follow `docs/LAB_TESTING.md` (IOSv/IOSvL2 first), then set `support: "tested"` in `catalog.json` |
| 6 | The AI assistant has only been tested against a fake provider | Test | 2 | 3 | 2 | 20 | **Needs the author:** install Ollama (free) or add a Groq/Gemini key, then follow `docs/AI_ASSISTANT.md` "Providers" |
| 7 | `services/jobs.py` (765 lines) holds both the job lifecycle (create/approve/reject) and the worker (`JobRunner`, `Execution`) | Code | 2 | 1 | 2 | 12 | Open. Low priority: well commented and fully tested. Split into `jobs.py` + `runner.py` when it next grows |
| 8 | MongoDB runs without access control | Infrastructure | 2 | 3 | 3 | 15 | Documented (`SECURITY.md` limitation 3); enable it on a shared PC |
| 9 | Two-person approval relies on the device's address: a second record for the same device under another address is not linked to the production one | Security design | 2 | 2 | 3 | 12 | Open (5B security review: needs the device login anyway, so no new access). Fix idea: refuse a new device whose SSH host key is already pinned for a production device |
| 11 | Custom commands are checked against a denylist of keywords; every vendor feature that stores CLI text and runs it later (schedulers, event handlers, macros) is a bypass until its keyword is added | Security design | 3 | 3 | 4 | 12 | Open (5C code review). Known features are denied for every driver. Stronger fix: an allowlist of top-level commands per driver for the custom-commands box |
| 10 | SNMPv3 status polling was not built (needs `pysnmp`, a new library) | Feature gap | 2 | 1 | 3 | 9 | Open; TCP/ping status is used instead |
