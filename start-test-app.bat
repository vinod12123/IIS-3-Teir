@echo off
setlocal

call :main
set "RESULT=%errorlevel%"
echo.
if "%RESULT%"=="0" (
  echo Script finished. Review the messages above, then press any key to close this window.
) else (
  echo Setup did not finish. Read the error above, then press any key to close this window.
)
pause >nul
exit /b %RESULT%

:main

set "APP_DIR=%~dp0IIS-Observability-Test"
set "SITE_DIR=C:\inetpub\wwwroot\IIS-Observability-Test"

if not exist "%APP_DIR%\frontend\package.json" (
  echo ERROR: Cannot find IIS-Observability-Test next to this batch file.
  exit /b 1
)

where docker >nul 2>&1
if errorlevel 1 (
  echo ERROR: Docker Desktop is required. Install and start it, then run this file again.
  exit /b 1
)
docker info >nul 2>&1
if errorlevel 1 (
  echo ERROR: Docker Desktop is not running. Start it, then run this file again.
  exit /b 1
)
docker compose version >nul 2>&1
if errorlevel 1 (
  echo ERROR: Docker Compose is unavailable.
  exit /b 1
)
where npm >nul 2>&1
if errorlevel 1 (
  echo ERROR: Node.js and npm are required.
  exit /b 1
)
where py >nul 2>&1
if not errorlevel 1 (
  set "PYTHON_CMD=py -3"
) else (
  where python >nul 2>&1
  if errorlevel 1 (
    echo ERROR: Python 3 is required.
    exit /b 1
  )
  set "PYTHON_CMD=python"
)

fltmc >nul 2>&1
if errorlevel 1 (
  echo ERROR: Run this file from an Administrator Command Prompt to deploy to IIS.
  exit /b 1
)
if not exist "%SystemRoot%\System32\inetsrv\appcmd.exe" (
  echo ERROR: IIS is not installed. Enable IIS with Static Content first.
  exit /b 1
)

cd /d "%APP_DIR%"
if not exist ".env" (
  copy /Y ".env.example" ".env" >nul
  echo Created %APP_DIR%\.env
  echo Edit POSTGRES_PASSWORD and the password in DATABASE_URL to the same private test password.
  echo Then run this file again.
  exit /b 0
)
findstr /C:"replace-me" ".env" >nul 2>&1
if not errorlevel 1 (
  echo ERROR: Set a private test password in .env before starting the app.
  exit /b 1
)

echo Starting the test database...
docker compose --env-file ".env" -f "database\compose.yml" up -d
if errorlevel 1 goto :failed

if not exist ".venv\Scripts\python.exe" (
  echo Creating Python environment...
  %PYTHON_CMD% -m venv ".venv"
  if errorlevel 1 goto :failed
)
echo Installing API dependencies...
".venv\Scripts\python.exe" -m pip install -r "backend\requirements.txt"
if errorlevel 1 goto :failed

echo Installing and building the frontend...
pushd "frontend"
call npm install
if errorlevel 1 (
  popd
  goto :failed
)
call npm run build
if errorlevel 1 (
  popd
  goto :failed
)
popd

echo Copying the built frontend into IIS...
robocopy "frontend\dist" "%SITE_DIR%" /E /R:2 /W:1 >nul
if errorlevel 8 goto :failed
copy /Y "iis\web.config" "%SITE_DIR%\web.config" >nul
if errorlevel 1 goto :failed

echo Starting the API in a separate window...
start "IIS Test API" /D "%APP_DIR%" cmd /k ".venv\Scripts\python.exe -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port 8008"
if errorlevel 1 goto :failed

echo.
echo Open http://localhost/IIS-Observability-Test/
echo Keep the IIS Test API window open while testing.
echo IIS requires URL Rewrite and ARR proxy mode for the API route.
exit /b 0

:failed
echo ERROR: Setup stopped. Read the error above, then run this file again.
exit /b 1
