# IIS three-tier observability test

This standalone lab has three running tiers:

```text
Browser → IIS static React frontend → IIS reverse proxy → FastAPI (127.0.0.1:8008) → PostgreSQL
```

The React UI now has a Products page and a Simulation page. Products are real PostgreSQL rows with add, edit, delete, stock counts, and inventory value. The Simulation page shows tier status, real outage controls, request scenarios, and bounded 8-request error bursts. The API writes JSON lines to `backend/logs/app.jsonl`; IIS writes its normal W3C access log. This is a test application, not a production service.

## One-command setup on the Windows IIS test machine

The Git repository contains this `IIS-Observability-Test` folder. After cloning the repository outside the IIS web root, install Python 3, Node.js, Docker Desktop, IIS Static Content, URL Rewrite, and Application Request Routing (ARR). In IIS Manager, enable ARR proxy mode at the server level once.

From an **Administrator Command Prompt** in the cloned repository root, run:

```bat
start-test-app.bat
```

On the first run, the script creates `IIS-Observability-Test\.env` and stops. Edit that file so `POSTGRES_PASSWORD` and the password in `DATABASE_URL` are the same private test password; then run the script again. It starts PostgreSQL, installs API and frontend dependencies, builds the React frontend, copies only the built frontend and `web.config` into `C:\inetpub\wwwroot\IIS-Observability-Test`, and opens the local controller in a separate Command Prompt. The controller starts and supervises the API. Keep that controller window open while testing. Visit `http://localhost/IIS-Observability-Test/` and check that API and database health both say `ok`.

For remote simulation controls, also set `LAB_CONTROL_USER=admin` and `LAB_CONTROL_PASSWORD` to your chosen test password in the server's ignored `.env` file. The example deliberately contains a placeholder; the password is never stored in the frontend source or Git. If `.env` was created with an older version of this lab, add these two lines manually before rerunning `start-test-app.bat`. The batch file redeploys the IIS rewrite rule and restarts the loopback controller; close the previous controller window before rerunning it.

From another computer, open `http://<test-server>/IIS-Observability-Test/#/simulation`, enter the controller credentials, then use the simulation buttons. These requests go through this app's IIS `/lab-control/` reverse proxy to the controller on `127.0.0.1:8010`; the controller port itself remains inaccessible over the network. If the frontend is stopped, use `http://<test-server>/IIS-Observability-Test/lab-control/recovery` to restore it. The remote recovery page asks for the same credentials. Use HTTPS for remote control: HTTP Basic credentials are readable on the network when the site is served over plain HTTP.

For later source updates, close the existing controller window (and any API window left from an older version), run `git pull` in the cloned repository, and rerun `start-test-app.bat`. The script does not install IIS modules or register the API as a Windows service; it is intended for an attended test machine.

### Real outage controls

Open the application **on the Windows test machine**. Its outage panel uses a controller bound only to `127.0.0.1:8010`:

- **Stop API** terminates only the Python API process launched by the controller. **Restore API** launches it again.
- **Stop database** stops only this Compose stack's `postgres` container. **Restore database** starts that container; its Docker volume retains the test records. Docker Desktop itself stays running so restoration remains possible.
- **Stop frontend** removes this app's deployed `index.html` from IIS until restored. It does not stop the Default Web Site or other IIS applications. The loaded browser tab can still use its restore button; a fresh page load will fail while the frontend is stopped.
- **API route unavailable** temporarily changes this app's IIS `web.config` proxy target to an unused loopback port. Restore puts its saved config back. This does not add a firewall rule or change other sites.
- **CPU pressure** starts one bounded Python worker for at most 60 seconds. **Disk usage increase** writes a removable 128 MB file only when at least 2 GB is free. Restore stops the worker or removes the file.
- **Real API exception** sends a request that raises a Python exception and records an API error without stopping the process.

The independent local recovery page at `http://127.0.0.1:8010/` remains available on the test server if the main page cannot reload. The authenticated `/lab-control/recovery` route is available from another computer. Keep one of those URLs handy before stopping the frontend. Rerunning `start-test-app.bat` also redeploys the frontend and starts the database. The controller binds to the test machine's loopback interface and accepts only named lab operations. The existing **Unhandled exception** and **Database query error** scenarios generate real Python/PostgreSQL failures without stopping a tier.

When PostgreSQL is stopped, `/api/health` returns HTTP 503 with `database: unavailable`. When the API is stopped, IIS records a proxy failure. When the frontend index is stopped, a new page load fails in IIS. These are actual tier outages, so restore the stopped tier from the recovery page after observing it.

The agent's IIS file source (`C:\inetpub\logs\LogFiles\W3SVC1`) captures HTTP statuses. To see Python error details in ASTRA, separately collect `backend\logs\app.jsonl` as an agent file-log source and grant `NT SERVICE\observe-agent` read access to that directory. Tier outages appear in ASTRA only when the corresponding host, service, container, or synthetic monitoring is enabled.

## Run locally for development

1. Copy `.env.example` to `.env` and replace `replace-me` with a private test password. `.env` is ignored by Git. Use a **dedicated** test database.
2. Start PostgreSQL with Docker, or install PostgreSQL separately and adjust `DATABASE_URL` in `.env`:

   ```powershell
   docker compose --env-file .env -f database\compose.yml up -d
   ```

3. Install and start the API from this directory:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
   .\.venv\Scripts\python.exe -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port 8008
   ```

4. In another terminal, start the React development server:

   ```powershell
   cd frontend
   npm install
   npm run dev
   ```

Open `http://localhost:5173/`. Vite proxies `/api` to FastAPI during development. The API remains running in its terminal; for a persistent IIS deployment, run it under a supervised Windows service.

## Deploy the React frontend under IIS

1. On the Windows test machine, install IIS **Static Content**, **URL Rewrite**, and **Application Request Routing (ARR)**. Enable proxy mode in ARR at the IIS server level. IIS needs the reverse proxy rule to forward `/api/*` to FastAPI on `127.0.0.1:8008`.
2. Start PostgreSQL and the API as above on the same test machine. Confirm `http://127.0.0.1:8008/api/health` reports `"api":"ok"` and `"database":"ok"`.
3. Build and copy the frontend. Adjust the IIS folder if your site uses a different path:

   ```powershell
   cd frontend
   npm install
   npm run build
   cd ..
   robocopy frontend\dist C:\inetpub\wwwroot\IIS-Observability-Test /E /R:2 /W:1
   Copy-Item iis\web.config C:\inetpub\wwwroot\IIS-Observability-Test\web.config -Force
   ```

4. Open `http://localhost/IIS-Observability-Test/` and check the three health cards. The API and database should both read **ok**. The React files are static; Classic ASP is not required for this new UI.

For a Git-based update on the other machine, clone this **standalone** application outside the IIS web root, pull updates there, rebuild `frontend`, then copy only `frontend/dist` and `iis/web.config` into the IIS site. Never deploy `.git`, `.env`, `backend`, or `database` into the web root. Updating API code also requires restarting its Windows service. No part of this application belongs in the ASTRA `Observability` repository.

## What to expect in ASTRA

- Collect the IIS W3C logs from the test site **and** `backend/logs/app.jsonl` from the installed Windows agent. Give `NT SERVICE\observe-agent` read access to both locations. The API file log contains `level: ERROR` on 500/503 responses and includes a request ID for correlation.
- Run **30 healthy requests**, then **8 API errors** or **8 database errors**. Verify the responses in this page, then look for matching entries in ASTRA **Observability → Logs** and **Errors**, followed by the host's **Error spike** monitor. Automatic incident creation still requires a critical check and **Open an incident for every critical alert** in the remediation settings.
- **Read database** and **Write database** exercise a real PostgreSQL connection. **Database query error** sends a query to a deliberately nonexistent table; it does not change schema or stop PostgreSQL. **Slow database query** uses a bounded two-second `pg_sleep`.
- To test a real database outage, stop only this test database from its own service/Compose stack, refresh the page, and then restore it. The database health card should change to **unavailable** while the API stays up.

## Legacy Classic ASP test

The root `index.html`, `api.asp`, `health.asp`, and `Generate-Traffic.ps1` are retained for the earlier Classic ASP scenarios. They are separate from the React/FastAPI/PostgreSQL application above. The instructions below apply only when deploying those legacy files.

## Legacy setup — Windows 11

A small **HTML + Classic ASP** app for testing real HTTP 200/400/404/500 codes, ~2-second latency, HTTP access logs, and request rates in Windows IIS. No external packages. Intended for a local test machine, **not a production/public server**.

## Install / update

1. Press **Win + R**, enter `optionalfeatures`.
2. Under **Internet Information Services → World Wide Web Services**, enable:
   - **Application Development Features → ASP** (**Classic ASP**, not merely ASP.NET).
   - **Common HTTP Features → Static Content** and **Default Document**.
   - **Health and Diagnostics → HTTP Logging**.
3. Extract the archive. Copy `index.html`, `api.asp` and `health.asp` to `C:\inetpub\wwwroot\IIS-Observability-Test\`, **overwriting old files**. Keep source-control files and `Generate-Traffic.ps1` outside the web root.
4. In IIS Manager (`inetmgr`) verify **Default Web Site → IIS-Observability-Test** exists; right-click its folder and **Convert to Application** if necessary. Set an app pool configured for Classic ASP (Integrated pipeline; defaults usually work).
5. Visit `http://localhost/IIS-Observability-Test/` and use **Check IIS / ASP endpoints**. Use Ctrl+F5 if cached.

### Updating the other Windows machine with Git

This test app can live in its **own Git repository**. Clone that repository outside the IIS web root on the machine running the agent, then pull and copy only the three served files into the IIS application directory:

```powershell
git clone <your-iis-test-repository-url> C:\src\IIS-Observability-Test
git -C C:\src\IIS-Observability-Test pull --ff-only
robocopy C:\src\IIS-Observability-Test C:\inetpub\wwwroot\IIS-Observability-Test index.html api.asp health.asp /R:2 /W:1
```

For later updates, repeat the last two commands. The Git repository is separate from ASTRA's `Observability` repository. Do not place the `.git` directory in the IIS site. The repository URL is supplied when you create or choose a remote for this test app.

> Important: the browser dashboard and its **Start traffic** timer can appear to work even when `.asp` endpoints do not execute. This version explicitly checks `health.asp` and shows response status, body, and pass/mismatch.

## Expected results

| Button | Actual endpoint | Expected HTTP | Notes |
| --- | --- | --- | --- |
| Healthy | `api.asp?mode=ok` | 200 | Executes Classic ASP |
| Server error | `api.asp?mode=error` | 500 | Intentionally returned; does not cause a Windows Event Log exception |
| Slow response | `api.asp?mode=slow` | 200 after ~2 s | Simulates latency using a bounded busy loop; avoid high concurrency |
| Missing page | `does-not-exist-*.html` | 404 | IIS returns the 404; it may return an HTML body |
| Bad request | `api.asp?mode=badrequest` | 400 | Intentionally returned |
| Unhandled exception | `api.asp?mode=exception` | 500 | Real VBScript runtime error (division by zero). IIS returns 500.100 and records the ASP error (line, error code, `Division_by_zero`) in the access log's `cs-uri-query` field |
| Type mismatch | `api.asp?mode=typemismatch` | 500 | Real VBScript runtime error (ASP 0013), logged by IIS the same way |
| Simulated database failure | `api.asp?mode=dberror` | 500 | Uses an invalid provider to simulate a dependency failure; there is no real database. Access log marker `dberror <code>`, optional Windows **Application** event log error (source `WSH`), JSON with `eventLogged` |
| Event log error | `api.asp?mode=eventlog` | 500 | Access log marker `application_error ...` and an Application event log error |
| Upstream down | `api.asp?mode=unavailable` | 503 | Application event log warning |
| Forbidden / Unauthorized | `api.asp?mode=forbidden` / `unauthorized` | 403 / 401 | Returned status only |

`eventLogged` in the JSON is `false` when the app pool identity may not write to the Application log; the access log lines are still produced.

To see application failures in ASTRA, the agent must collect the IIS W3C access logs (`iis=C:\inetpub\logs\LogFiles\W3SVC1`, or the actual site folder) and `NT SERVICE\observe-agent` must be able to read them. Verify the site's W3C log includes `sc-status`. A 500/503 is classified as a failure; a 400/401/403/404 is a client response, and a slow 200 is a latency test. The UI now counts 4xx and 5xx separately.

Windows Event Log collection is **off by default** in the agent. Enable it when testing `eventlog`, `dberror` or `unavailable` events. These scenarios return HTTP 500/503 even if the app pool cannot write an Application event; their JSON `eventLogged` field shows whether that extra event was written. IIS log collection and Event Log collection are independent.

## ASTRA incident button

1. Leave **Include mixed errors** unchecked and run healthy traffic for several minutes so ASTRA has a baseline, then stop the traffic generator.
2. Press **Send 8 type mismatch errors**. The browser sends eight unique requests, two seconds apart, and displays how many returned 500.
3. Check the IIS W3C access log first, then ASTRA **Observability → Logs**, **Errors**, and the host's **Error spike (2 min, vs normal)** monitor. The error view needs collected logs; the monitor must reach critical to open an incident.
4. On `/manage/org/remediation`, enable **Open an incident for every critical alert** if you want automatic incident creation. An existing incident for the same check may absorb the burst. The button does not itself open an ASTRA incident.

This button tests the log-to-monitor path. If the browser shows eight 500 responses but ASTRA Logs has no matching records, check the agent's IIS log source, file permissions, collection status and selected time range. If ASTRA Logs has them but Errors does not, inspect the parsed `http.response.status_code` and severity on a log record.

**404 and 500 are successful results when expected.** Read the status, expected code, and PASS/MISMATCH in the request log. The browser's fetch API resolves for HTTP 4xx and 5xx; they are not network errors.

## Manual troubleshooting

Check in a browser:

- `http://localhost/IIS-Observability-Test/health.asp` should display `{"status":"healthy","service":"iis-observability-test"}`.
- `http://localhost/IIS-Observability-Test/api.asp?mode=ok` should return JSON and HTTP 200.
- If `.asp` gives **404.3**, ASP is not installed/allowed or handler mapping is missing. Enable the Classic ASP Windows feature.
- If **404.0**, verify the physical folder and IIS application path; verify `api.asp` exists.
- If **500.19**, inspect IIS configuration and permissions.
- If **500.100**, inspect Classic ASP errors / code.
- If an HTTP 500 body is replaced by an IIS HTML error page, the HTTP **500 code still works for monitoring**.
- Press **F12 → Network** to inspect request status; ensure no browser extension is intercepting requests.
- Default IIS access logs: `C:\inetpub\logs\LogFiles\W3SVC*\u_ex*.log`. Check site settings in IIS Manager → Logging.

## Generate traffic in PowerShell

```powershell
cd C:\inetpub\wwwroot\IIS-Observability-Test
Set-ExecutionPolicy -Scope Process Bypass
.\Generate-Traffic.ps1 -BaseUrl 'http://localhost/IIS-Observability-Test' -Requests 50
# add server failures (exceptions, simulated database failures, 503) every 5th request:
.\Generate-Traffic.ps1 -BaseUrl 'http://localhost/IIS-Observability-Test' -Requests 100 -AppErrors
```

## Telemetry notes

IIS HTTP log collection must be enabled/configured for the installed observability agent; hosting a test application alone does not guarantee traces, errors, or HTTP metrics. Host CPU/memory collection and Windows Event Log collection may be separate integrations. The intentional 500 is a **returned status**, not an unhandled application exception.
