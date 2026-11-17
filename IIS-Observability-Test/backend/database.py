"""PostgreSQL operations for the IIS three-tier test application."""

import os
from threading import Lock

import psycopg
from psycopg.rows import dict_row

_schema_lock = Lock()
_schema_ready = False


def connect():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg.connect(url, connect_timeout=3, row_factory=dict_row)


def initialize():
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        with connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS test_events (
                    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    scenario TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        _schema_ready = True


def read_count():
    initialize()
    with connect() as connection:
        return connection.execute("SELECT count(*) AS count FROM test_events").fetchone()["count"]


def write_event(scenario: str):
    initialize()
    with connect() as connection:
        return connection.execute(
            "INSERT INTO test_events(scenario) VALUES (%s) RETURNING id", (scenario,)
        ).fetchone()["id"]


def recent_events(limit: int = 20):
    initialize()
    with connect() as connection:
        return connection.execute(
            "SELECT id, scenario, created_at FROM test_events ORDER BY id DESC LIMIT %s",
            (limit,),
        ).fetchall()


def slow_query():
    initialize()
    with connect() as connection:
        connection.execute("SELECT pg_sleep(2)")
        return connection.execute("SELECT count(*) AS count FROM test_events").fetchone()["count"]


def failed_query():
    """A genuine PostgreSQL error in a disposable transaction; no schema is changed."""
    initialize()
    with connect() as connection:
        connection.execute("SELECT * FROM astra_test_missing_table")
