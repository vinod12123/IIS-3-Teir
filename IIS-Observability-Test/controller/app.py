"""Loopback-only controls for real outages in the dedicated IIS test lab."""

import asyncio
import shutil
import socket
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from threading import RLock
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse


ROOT = Path(__file__).resolve().parent.parent
SITE = Path(r"C:\inetpub\wwwroot\IIS-Observability-Test")
INDEX = SITE / "index.html"
DISABLED_INDEX = SITE / "index.html.lab-disabled"
PROXY_CONFIG = SITE / "web.config"
PROXY_BACKUP = SITE / "web.config.lab-original"
PROXY_TARGET = "http://127.0.0.1:8008/api/{R:1}"
BROKEN_TARGET = "http://127.0.0.1:8999/api/{R:1}"
DISK_LOAD = ROOT / "controller" / "lab-disk-load.bin"
API_LOG = ROOT / "backend" / "logs" / "api-console.log"
ORIGINS = {
    "http://localhost",
    "http://127.0.0.1",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8010",
    "http://localhost:8010",
}


class LabController:
    def __init__(self):
        self.lock = RLock()
        self.api_process: subprocess.Popen | None = None
        self.cpu_process: subprocess.Popen | None = None

    @staticmethod
    def _api_responding():
        try:
            with urlopen("http://127.0.0.1:8008/api/health", timeout=1) as response:
                return response.status in (200, 503)
        except HTTPError as error:
            return error.code == 503
        except (OSError, URLError):
            return False

    @staticmethod
    def _port_busy():
        with socket.socket() as connection:
            connection.settimeout(1)
            return connection.connect_ex(("127.0.0.1", 8008)) == 0

    @staticmethod
    def _compose(*arguments):
        try:
            completed = subprocess.run(
                ["docker", "compose", "--env-file", str(ROOT / ".env"), "-f", str(ROOT / "database" / "compose.yml"), *arguments],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeError(f"Docker command failed: {error}") from error
        if completed.returncode:
            raise RuntimeError((completed.stderr or completed.stdout).strip()[-600:] or "Docker Compose failed")
        return completed.stdout.strip()

    def status(self):
        with self.lock:
            try:
                database_running = bool(self._compose("ps", "--status", "running", "--quiet", "postgres"))
            except RuntimeError:
                database_running = False
            api_managed = self.api_process is not None and self.api_process.poll() is None
            cpu_active = self.cpu_process is not None and self.cpu_process.poll() is None
            route_config = PROXY_CONFIG.read_text(encoding="utf-8") if PROXY_CONFIG.is_file() else ""
            return {
                "frontend": "running" if INDEX.is_file() else "stopped",
                "api": "running" if api_managed and self._api_responding() else "stopped",
                "database": "running" if database_running else "stopped",
                "apiManaged": api_managed,
                "route": "running" if PROXY_TARGET in route_config else "stopped",
                "cpu": "running" if cpu_active else "stopped",
                "disk": "running" if DISK_LOAD.is_file() else "stopped",
            }

    def start_api(self):
        with self.lock:
            if self.api_process is not None and self.api_process.poll() is None:
                return
            if self._port_busy():
                raise RuntimeError("Port 8008 is occupied. Close the old IIS Test API window first.")
            API_LOG.parent.mkdir(parents=True, exist_ok=True)
            with API_LOG.open("a", encoding="utf-8") as log:
                self.api_process = subprocess.Popen(
                    [sys.executable, "-m", "uvicorn", "app:app", "--app-dir", "backend", "--host", "127.0.0.1", "--port", "8008"],
                    cwd=ROOT,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                )
            for _ in range(50):
                if self.api_process.poll() is not None:
                    raise RuntimeError(f"API exited during startup. Check {API_LOG}.")
                if self._api_responding():
                    return
                time.sleep(0.2)
            raise RuntimeError(f"API did not become ready. Check {API_LOG}.")

    def stop_api(self):
        with self.lock:
            if self.api_process is None or self.api_process.poll() is not None:
                raise RuntimeError("This controller does not own a running API process.")
            self.api_process.terminate()
            try:
                self.api_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.api_process.kill()
                self.api_process.wait(timeout=5)
            self.api_process = None

    def stop_database(self):
        with self.lock:
            self._compose("stop", "postgres")

    def start_database(self):
        with self.lock:
            self._compose("up", "-d", "postgres")

    def stop_frontend(self):
        with self.lock:
            if not INDEX.is_file():
                raise RuntimeError(f"IIS frontend is already unavailable at {INDEX}.")
            if DISABLED_INDEX.exists():
                raise RuntimeError(f"Stale disabled frontend file exists at {DISABLED_INDEX}.")
            INDEX.replace(DISABLED_INDEX)

    def start_frontend(self):
        with self.lock:
            if INDEX.is_file():
                if DISABLED_INDEX.exists():
                    DISABLED_INDEX.unlink()
                return
            if not DISABLED_INDEX.is_file():
                raise RuntimeError("No saved frontend index exists. Rerun start-test-app.bat to deploy it.")
            DISABLED_INDEX.replace(INDEX)

    def stop_route(self):
        with self.lock:
            if not PROXY_CONFIG.is_file():
                raise RuntimeError("Deployed IIS web.config is missing.")
            current = PROXY_CONFIG.read_text(encoding="utf-8")
            if PROXY_TARGET not in current or PROXY_BACKUP.exists():
                raise RuntimeError("The lab API route is already changed or has a stale backup.")
            shutil.copy2(PROXY_CONFIG, PROXY_BACKUP)
            temporary = PROXY_CONFIG.with_name("web.config.lab-temp")
            temporary.write_text(current.replace(PROXY_TARGET, BROKEN_TARGET, 1), encoding="utf-8")
            temporary.replace(PROXY_CONFIG)

    def start_route(self):
        with self.lock:
            if PROXY_BACKUP.is_file():
                PROXY_BACKUP.replace(PROXY_CONFIG)
            elif not PROXY_CONFIG.is_file() or PROXY_TARGET not in PROXY_CONFIG.read_text(encoding="utf-8"):
                raise RuntimeError("No saved IIS route exists. Rerun start-test-app.bat to deploy web.config.")

    def start_cpu(self):
        with self.lock:
            if self.cpu_process is not None and self.cpu_process.poll() is None:
                return
            worker = (
                "import time; end=time.monotonic()+60; value=1\n"
                "while time.monotonic()<end: value=(value*1103515245+12345)&0xffffffff\n"
            )
            self.cpu_process = subprocess.Popen([sys.executable, "-c", worker], cwd=ROOT)

    def stop_cpu(self):
        with self.lock:
            if self.cpu_process is not None and self.cpu_process.poll() is None:
                self.cpu_process.terminate()
                try:
                    self.cpu_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.cpu_process.kill()
                    self.cpu_process.wait(timeout=5)
            self.cpu_process = None

    def start_disk(self):
        with self.lock:
            if DISK_LOAD.exists():
                return
            if shutil.disk_usage(DISK_LOAD.parent).free < 2 * 1024**3:
                raise RuntimeError("At least 2 GB free space is required for the bounded disk test.")
            try:
                with DISK_LOAD.open("wb") as output:
                    block = b"\0" * (1024 * 1024)
                    for _ in range(128):
                        output.write(block)
            except OSError as error:
                DISK_LOAD.unlink(missing_ok=True)
                raise RuntimeError(f"Could not create bounded disk load: {error}") from error

    def stop_disk(self):
        with self.lock:
            DISK_LOAD.unlink(missing_ok=True)


controller = LabController()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    controller.start_frontend()
    controller.start_route()
    controller.start_api()
    try:
        yield
    finally:
        if controller.api_process is not None and controller.api_process.poll() is None:
            controller.stop_api()
        controller.stop_cpu()
        controller.stop_disk()


app = FastAPI(title="IIS test lab controller", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=sorted(ORIGINS), allow_methods=["GET", "POST"], allow_headers=["X-Lab-Control"])


@app.get("/")
def control_page():
    return FileResponse(Path(__file__).with_name("control.html"))


@app.get("/control/status")
async def status():
    return await asyncio.to_thread(controller.status)


@app.post("/control/{tier}/{action}")
async def change_state(tier: str, action: str, request: Request, x_lab_control: str | None = Header(default=None)):
    if request.headers.get("origin") not in (None, *ORIGINS) or x_lab_control != "local-lab":
        raise HTTPException(status_code=403, detail="Local test-lab request required")
    operations = {
        ("api", "stop"): controller.stop_api,
        ("api", "restore"): controller.start_api,
        ("database", "stop"): controller.stop_database,
        ("database", "restore"): controller.start_database,
        ("frontend", "stop"): controller.stop_frontend,
        ("frontend", "restore"): controller.start_frontend,
        ("route", "stop"): controller.stop_route,
        ("route", "restore"): controller.start_route,
        ("cpu", "stop"): controller.start_cpu,
        ("cpu", "restore"): controller.stop_cpu,
        ("disk", "stop"): controller.start_disk,
        ("disk", "restore"): controller.stop_disk,
    }
    operation = operations.get((tier, action))
    if operation is None:
        raise HTTPException(status_code=404, detail="Unknown lab operation")
    try:
        await asyncio.to_thread(operation)
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"tier": tier, "action": action, "status": await asyncio.to_thread(controller.status)}
