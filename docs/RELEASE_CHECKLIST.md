# Release checklist

NetConfig Studio is not deployed to a server: a "release" is a tagged commit that an engineer installs on
their own Windows 11 PC and starts with `scripts\start.ps1`. Go through this list for every release, even a
small one, and fill in the run record at the bottom.

**Version:** `backend/app/__init__.py` (`__version__`) and `frontend/package.json` (`version`) — keep them equal.

## 1. Before the release

### Code and tests
- [ ] Working tree clean, on the release branch, everything committed (`git status`).
- [ ] `powershell -ExecutionPolicy Bypass -File scripts\check.ps1` → **every line PASS**. This runs pytest
      (database tests *fail* without MongoDB, they are never skipped), ruff, bandit, pip-audit (only the IDs in
      `docs/ACCEPTED_RISKS.md` are ignored), vitest, the production build and npm audit.
- [ ] `/code-review` and `/security-review` run on the changes since the last release; every confirmed finding
      fixed or written down in `docs/TECH_DEBT.md` / `docs/SECURITY.md` limitations.
- [ ] Golden-file changes (`tests/golden/**`) read line by line against the vendor documentation.

### Security (CLAUDE.md §8)
- [ ] `docs/SECURITY.md` §5 compliance table still true: no rule weakened, every new route in the RBAC table
      test (`test_rbac_table_covers_every_route`).
- [ ] `docs/ACCEPTED_RISKS.md` reviewed: each row still has a valid reason; remove rows whose exit condition
      is met (and the IDs drop out of `check.ps1` automatically).
- [ ] No secrets in the repository: `git grep -n -i -E "password\s*=|secret\s*=|api_key\s*=" -- ':!*.md' ':!tests'`
      shows only code, never values; `backend\.env` is not tracked (`git ls-files backend/.env` prints nothing).
- [ ] `backend/.env.example` defaults are safe: `HOST=127.0.0.1`, `ALLOW_REMOTE=false`, `ENV=development`,
      `ENABLE_EXPERIMENTAL_DRIVERS=false`, `AI_PROVIDER=off`, no key values.

### Drivers
- [ ] `docs/drivers/README.md` table matches `catalog.json` support levels. A driver is `tested` only with a
      dated `docs/LAB_TESTING.md` run behind it.
- [ ] Experimental drivers are still off by default (`test_loaded_only_with_the_flag`).

### Documentation
- [ ] `README.md` progress table and "Security in one minute" are current.
- [ ] `docs/USER_GUIDE.md` matches the UI (labels, steps, statuses).
- [ ] `docs/diagrams/*.html` regenerated with archify if the architecture or the push flow changed.
- [ ] Release notes written (section 4).

### Data
- [ ] Database changes are backward compatible: the app must start on an existing `netconfig` database
      (new fields have defaults; indexes are created at start by `ensure_indexes`).
- [ ] If the catalog changed: `scripts\seed_catalog.py` (without `--reset`) keeps existing inventory devices
      pointing at valid models.

## 2. Install / upgrade on the engineer's PC

1. **Back up MongoDB first** (the rollback depends on it). With the free *MongoDB Database Tools*:
   ```powershell
   mongodump --uri mongodb://127.0.0.1:27017 --db netconfig --out "$env:USERPROFILE\netconfig-backup\$(Get-Date -Format yyyyMMdd-HHmm)"
   ```
   The dump holds masked backups, job history, password hashes and the audit log, so keep it in the user's
   profile, never on a share.
2. Stop the running app (Ctrl+C in its window).
3. `git fetch --tags` and `git checkout v<version>`.
4. `powershell -ExecutionPolicy Bypass -File scripts\dev-backend.ps1` once (installs the pinned packages), stop
   it, then `cd frontend; npm ci`.
5. `powershell -ExecutionPolicy Bypass -File scripts\start.ps1`.

## 3. Smoke test after starting (5 minutes)

- [ ] `start.ps1` prints "MongoDB is reachable" and the URL; the browser opens it.
- [ ] `GET /api/health` → `{"status": "ok", "mongo": "ok", "simulation": false}`.
- [ ] `/docs` and `/openapi.json` return 404 (production).
- [ ] A request with `Host: evil.example` gets 400 (`docs/SECURITY_TESTING.md` §1).
- [ ] Sign in; Overview, Devices, Catalog and History load with no console or CSP errors.
- [ ] Admin → Audit log shows "Hash chain intact".
- [ ] On a **lab** device (or `SIMULATE_DEVICES=true` with `ENV=development`): preview a small VLAN plan,
      create the job, run it, and see *success* in History with a masked transcript.

## 4. Release notes and tag

- [ ] Bump the version in both files, commit "Release v<version>".
- [ ] `git tag -a v<version> -m "NetConfig Studio v<version>"` and push the tag.
- [ ] Release notes: what changed, which drivers are tested vs experimental, accepted risks, upgrade notes.

## 5. Rollback

**Roll back when:** the app does not start on the existing database; sign-in fails for valid users; any push
reports `failed` where the previous version succeeded on the same lab device; or a security check from
section 3 fails.

1. Stop the app.
2. `git checkout v<previous version>`, then `scripts\dev-backend.ps1` once and `npm ci` (older pinned packages).
3. Only if the new version changed data: `mongorestore --uri mongodb://127.0.0.1:27017 --drop --nsInclude "netconfig.*" "<backup folder>"`.
4. `scripts\start.ps1` and repeat the smoke test.

Device configurations are not affected by an app rollback: each push already kept a backup of the running
config in its job, and devices with a rollback timer revert by themselves.

## Run record

| Date | Version / commit | By | Result | Notes |
|---|---|---|---|---|
| 2026-11-22 | `0.1.0`, Phase 5C (pre-tag) | Claude Code (for the author) | see below | First run of this checklist |

Run 2026-11-22, items checked automatically or by hand:

- `scripts\check.ps1` (full, with audits): result recorded in the Phase 5C commit message.
- Secrets grep, `.env` untracked, `.env.example` defaults: checked.
- `docs/drivers/README.md` vs `catalog.json`: all 8 drivers `experimental` (none `tested` yet: no lab run), 3 inventory types. Matches.
- Smoke test, production mode (`scripts\start.ps1 -NoBrowser`): health ok, frontend served, `/docs` 404.
- End-to-end against a live server with the simulated device (own `netconfig_e2e` database, dropped after):
  23/23 checks with default settings, 26/26 with `ENABLE_EXPERIMENTAL_DRIVERS=true`. They cover the Host,
  Origin and custom-header checks, httpOnly + SameSite=Strict cookie, preview, reserved-VLAN and `do rel`
  refusals, lab push → *success* with verification checks, no secret in the job record, MongoDB or server log,
  the production tag needing an admin, a production push refused while no driver is lab-tested (flag off),
  and the two-person rule (flag on). The audit hash chain was intact.
- **Not done (needs the author):** MongoDB backup (MongoDB Database Tools are not installed on this PC), the
  version bump and the release tag, the lab run of any driver (`docs/LAB_TESTING.md`), and a try of the AI
  assistant against a real provider.
