# Public demo on Render + MongoDB Atlas

This puts a **demo** of NetConfig Studio on `https://netconfig.munisaidivtih.in` for interviews and recruiters.
It is not a way to run the real tool in the cloud: a server in a data centre has no route to the switches and
routers in your network (CLAUDE.md §2). The real tool stays on the engineer's laptop.

## What DEMO_MODE does (and why)

| Setting | Local app (default) | Public demo (`DEMO_MODE=true`) |
|---|---|---|
| Devices | real SSH / Telnet / serial via Netmiko | simulated only (`SIMULATE_DEVICES=true` is required) |
| HTTPS | uvicorn with your own certificate when remote | done by Render's proxy; app refuses its own certificate settings |
| Host header allowlist | `127.0.0.1:<port>`, `localhost:<port>` | only `PUBLIC_HOST` (DNS-rebinding protection stays) |
| Origin check | same origin (+ Vite in dev) | only `https://PUBLIC_HOST` |
| Cookies | httpOnly, SameSite=Strict | + `Secure`, + HSTS header |
| `/docs`, `/openapi.json` | off in production | off (ENV must be production) |
| Client IP (login rate limit) | socket address | `X-Forwarded-For` from Render's proxy (the only way in) |
| Camera (ONVIF) reads | allowed | blocked: a public server must not call addresses visitors type in (SSRF) |
| AI assistant | optional | must be off (visitors would spend your API key) |

`DEMO_MODE` is all or nothing: if any of these settings is missing the app **refuses to start** and says which
one (`Settings.check_demo`, tested in `tests/security/test_demo_mode.py`). With `DEMO_MODE` unset nothing changes.

## Step 1 – MongoDB Atlas (free M0 cluster)

1. Sign up at <https://www.mongodb.com/cloud/atlas/register> and create a **free M0** cluster
   (provider AWS, region **Mumbai ap-south-1** or the one closest to the Render region you pick).
2. **Database Access → Add New Database User**
   - Username: `netconfig_demo`
   - Password: click *Autogenerate Secure Password* and copy it somewhere safe.
   - *Built-in role*: choose **Specific privileges → `readWrite` on database `netconfig_demo`** (not *Atlas admin*).
3. **Network Access → Add IP Address → Allow access from anywhere (`0.0.0.0/0`)**.
   Render's free plan has no fixed outgoing IP, so this is the only option. It is why step 2 uses a long
   random password and a user that can touch only the demo database.
4. **Database → Connect → Drivers → Python** and copy the connection string. It looks like
   `mongodb+srv://netconfig_demo:<password>@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority`.
   Replace `<password>` with the password from step 2. **Never commit this string.**

## Step 2 – Create the demo accounts in Atlas (from your laptop)

The admin is created with the same script as locally, just pointed at Atlas. In PowerShell:

```powershell
cd "D:\POJECTS\NETWORKING PROJECT\NETCONFIG\backend"
$env:MONGO_URI = "mongodb+srv://netconfig_demo:...@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority"
$env:MONGO_DB = "netconfig_demo"
$env:MONGO_TIMEOUT_MS = "10000"
.venv\Scripts\python scripts\create_user.py admin --role admin        # your own account (keep it private)
.venv\Scripts\python scripts\create_user.py demo --role engineer      # the account you give recruiters
Remove-Item Env:MONGO_URI, Env:MONGO_DB, Env:MONGO_TIMEOUT_MS         # back to the local database
```

The catalog is seeded automatically the first time the Render app starts.

**Or copy your local database instead** (users, catalog, audit log with its hash chain, devices, jobs). It asks
for the Atlas string at a hidden prompt; sessions (live login tokens) are never copied:

```powershell
.venv\Scripts\python scripts\copy_database.py              # into netconfig_demo; existing data is kept
.venv\Scripts\python scripts\copy_database.py --replace    # empty the Atlas collections first
```

## Step 3 – Put the code on GitHub

Render deploys from a Git repository. Commit your work and push the branch you want to deploy
(for example `main`) to a GitHub repository. Check first that `backend/.env` is **not** in it (`git status`;
it is in `.gitignore`).

## Step 4 – Create the Render service

1. Sign up at <https://render.com> with GitHub (free; no card needed for the free web service).
2. **New → Blueprint**, pick your repository. Render reads `render.yaml` from the repository root and shows the
   `netconfig-demo` web service.
3. It asks for the one secret value, **`MONGO_URI`**: paste the Atlas string from step 1.
4. Click **Apply**. The build installs the Python packages, then builds the React frontend with Node
   (`npm ci && npm run build`). The first build takes a few minutes.
5. Open **Logs**. You should see `DEMO_MODE=true: public demo on https://netconfig.munisaidivtih.in ...` and
   `Uvicorn running on http://0.0.0.0:10000`. If a demo setting is missing, the log says which one.

Opening `https://netconfig-demo.onrender.com` now shows **"Host not allowed"**. That is correct: only the
custom domain is accepted (DNS-rebinding protection). Continue with step 5.

> Do not set a *Health Check Path* in Render: Render's health checker does not send your domain as the Host
> header, so it would be refused and Render would keep restarting the service.

## Step 5 – Point the subdomain at Render

1. In Render: service → **Settings → Custom Domains → Add** `netconfig.munisaidivtih.in`.
   Render shows the record to create, normally **CNAME `netconfig` → `netconfig-demo.onrender.com`**.
2. At the company where you bought `munisaidivtih.in` (GoDaddy, Hostinger, Cloudflare, …) open **DNS** and add:

   | Type | Name / Host | Value / Points to | TTL |
   |---|---|---|---|
   | CNAME | `netconfig` | `netconfig-demo.onrender.com` | default |

   On Cloudflare set the record to **DNS only** (grey cloud) so Render can issue its certificate.
3. Back in Render click **Verify**. When DNS has spread (minutes, sometimes up to an hour) Render issues a free
   HTTPS certificate automatically.
4. Open `https://netconfig.munisaidivtih.in`, sign in as `demo`, add a device (any private IP; it is simulated),
   configure a VLAN and push. The yellow **Public demo** banner shows on every page.

## Step 6 – After it works

- Free Render services **sleep after 15 minutes** without visitors; the first visit after that takes ~1 minute.
- `autoDeploy` is off: deploy new code with **Manual Deploy → Deploy latest commit**.
- Anyone with the `demo` login can change its password. If that happens, reset it as `admin` on the
  **Security** page.
- Atlas free tier: 512 MB. To start fresh, drop the `netconfig_demo` database in Atlas and recreate the users
  (step 2).
- Changing the domain later: update `PUBLIC_HOST` in Render's *Environment* tab and the custom domain.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Log: `DEMO_MODE=true needs: ...` | A demo env var is missing or wrong; the message names it. |
| Page loads, `/api/health` says `"mongo": "down"` | Wrong `MONGO_URI` password, or Atlas *Network Access* lacks `0.0.0.0/0`. |
| `Host not allowed.` on the custom domain | `PUBLIC_HOST` differs from the address in the browser (check spelling, lowercase, no `https://`). |
| Login works, then every click says *Origin not allowed* | Same as above: `PUBLIC_HOST` must match the domain exactly. |
| Build fails at `npm ci` | Node missing: keep `NODE_VERSION` in the environment (it is in `render.yaml`). |
