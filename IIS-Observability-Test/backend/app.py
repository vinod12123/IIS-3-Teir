"""Three-tier IIS observability test API. Run only on a dedicated test machine."""

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from uuid import uuid4

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import database


ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logger = logging.getLogger("iis_test")
logger.setLevel(logging.INFO)
logger.propagate = False
formatter = logging.Formatter("%(message)s")
for handler in (logging.StreamHandler(), RotatingFileHandler(LOG_DIR / "app.jsonl", maxBytes=5_000_000, backupCount=3)):
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def emit(level: str, event: str, **fields):
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "event": event,
        **fields,
    }
    logger.log(getattr(logging, level), json.dumps(record, default=str))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        database.initialize()
        emit("INFO", "database_ready")
    except (psycopg.Error, RuntimeError) as error:
        emit("WARNING", "database_unavailable_at_start", error=type(error).__name__)
    yield


app = FastAPI(title="IIS three-tier observability test", lifespan=lifespan)


class ProductInput(BaseModel):
    sku: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9-]+$")
    name: str = Field(min_length=1, max_length=100)
    category: str = Field(min_length=1, max_length=50)
    quantity: int = Field(ge=0, le=1_000_000)
    reorder_level: int = Field(ge=0, le=1_000_000)
    unit_price: float = Field(ge=0, le=1_000_000)


class ProductUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    category: str = Field(min_length=1, max_length=50)
    quantity: int = Field(ge=0, le=1_000_000)
    reorder_level: int = Field(ge=0, le=1_000_000)
    unit_price: float = Field(ge=0, le=1_000_000)


@app.middleware("http")
async def request_log(request: Request, call_next):
    started = time.perf_counter()
    request_id = uuid4().hex[:12]
    try:
        response = await call_next(request)
    except Exception as error:
        emit("ERROR", "unhandled_api_error", request_id=request_id, error=type(error).__name__)
        response = JSONResponse(status_code=500, content={"status": "error", "scenario": "api-exception", "message": "Unhandled API exception", "requestId": request_id})
    duration_ms = round((time.perf_counter() - started) * 1000)
    level = "ERROR" if response.status_code >= 500 else "WARNING" if response.status_code >= 400 else "INFO"
    emit(level, "http_request", request_id=request_id, method=request.method, path=request.url.path, status_code=response.status_code, duration_ms=duration_ms)
    response.headers["X-Test-Request-Id"] = request_id
    response.headers["Cache-Control"] = "no-store"
    return response


def result(scenario: str, status_code: int, message: str, **details):
    return JSONResponse(status_code=status_code, content={"status": "ok" if status_code < 400 else "error", "scenario": scenario, "message": message, **details})


@app.get("/api/health")
def health():
    try:
        count = database.read_count()
        return {"api": "ok", "database": "ok", "eventCount": count}
    except (psycopg.Error, RuntimeError) as error:
        emit("WARNING", "database_health_failed", error=type(error).__name__)
        return JSONResponse(status_code=503, content={"api": "ok", "database": "unavailable", "eventCount": None})


@app.get("/api/events")
def events():
    try:
        return {"events": database.recent_events()}
    except (psycopg.Error, RuntimeError) as error:
        emit("ERROR", "database_events_failed", error=type(error).__name__)
        return result("events", 503, "Database unavailable")


@app.get("/api/products")
def products():
    try:
        return {"products": database.list_products()}
    except (psycopg.Error, RuntimeError) as error:
        emit("ERROR", "product_list_failed", error=type(error).__name__)
        return result("products", 503, "Inventory database unavailable")


@app.post("/api/products", status_code=201)
def add_product(item: ProductInput):
    try:
        return database.create_product(item)
    except psycopg.errors.UniqueViolation:
        return result("products", 409, "SKU already exists")
    except (psycopg.Error, RuntimeError) as error:
        emit("ERROR", "product_create_failed", error=type(error).__name__)
        return result("products", 503, "Inventory database unavailable")


@app.put("/api/products/{product_id}")
def edit_product(product_id: int, item: ProductUpdate):
    try:
        product = database.update_product(product_id, item)
        return product if product else result("products", 404, "Product not found")
    except (psycopg.Error, RuntimeError) as error:
        emit("ERROR", "product_update_failed", error=type(error).__name__)
        return result("products", 503, "Inventory database unavailable")


@app.delete("/api/products/{product_id}")
def remove_product(product_id: int):
    try:
        return {"deleted": bool(database.delete_product(product_id))}
    except (psycopg.Error, RuntimeError) as error:
        emit("ERROR", "product_delete_failed", error=type(error).__name__)
        return result("products", 503, "Inventory database unavailable")


@app.post("/api/scenarios/{scenario}")
async def scenario(scenario: str):
    if scenario == "healthy":
        return result(scenario, 200, "API is healthy")
    if scenario == "api-error":
        return result(scenario, 500, "Deliberate API server error")
    if scenario == "api-exception":
        raise RuntimeError("Deliberate test exception")
    if scenario == "slow-api":
        await asyncio.sleep(2)
        return result(scenario, 200, "API took two seconds")
    if scenario == "upstream-unavailable":
        return result(scenario, 503, "Simulated upstream dependency unavailable")
    if scenario not in {"db-read", "db-write", "slow-db", "db-error"}:
        return result(scenario, 404, "Unknown test scenario")

    try:
        if scenario == "db-read":
            count = await asyncio.to_thread(database.read_count)
            return result(scenario, 200, "Real PostgreSQL read succeeded", eventCount=count)
        if scenario == "db-write":
            event_id = await asyncio.to_thread(database.write_event, scenario)
            return result(scenario, 201, "Real PostgreSQL write succeeded", eventId=event_id)
        if scenario == "slow-db":
            count = await asyncio.to_thread(database.slow_query)
            return result(scenario, 200, "Real PostgreSQL query took two seconds", eventCount=count)
        await asyncio.to_thread(database.failed_query)
    except psycopg.OperationalError as error:
        emit("ERROR", "database_connection_failed", scenario=scenario, error=type(error).__name__)
        return result(scenario, 503, "PostgreSQL connection failed")
    except (psycopg.Error, RuntimeError) as error:
        emit("ERROR", "database_query_failed", scenario=scenario, error=type(error).__name__)
        if scenario == "db-error":
            return result(scenario, 500, "Deliberate PostgreSQL query failure")
        return result(scenario, 503, "PostgreSQL operation failed")
    return result(scenario, 500, "The expected PostgreSQL error did not occur")
