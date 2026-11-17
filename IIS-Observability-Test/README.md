# IIS Observability Test v3 — Windows 11

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
