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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS products (
                    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    sku TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    quantity INTEGER NOT NULL CHECK (quantity >= 0),
                    reorder_level INTEGER NOT NULL CHECK (reorder_level >= 0),
                    unit_price NUMERIC(12,2) NOT NULL CHECK (unit_price >= 0),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO products(sku,name,category,quantity,reorder_level,unit_price)
                    VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (sku) DO NOTHING
                    """,
                    [
                        ("STK-1001", "Wireless barcode scanner", "Devices", 34, 10, "89.00"),
                        ("STK-1002", "Thermal label printer", "Devices", 12, 5, "249.00"),
                        ("STK-1003", "Shipping labels · 500 pack", "Supplies", 148, 30, "18.50"),
                        ("STK-1004", "Inventory tote · blue", "Storage", 7, 12, "26.00"),
                        ("STK-1005", "USB-C charging dock", "Accessories", 0, 8, "39.00"),
                        ("STK-1006", "Handheld scanner battery", "Accessories", 23, 10, "44.00"),
                    ],
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


def list_products():
    initialize()
    with connect() as connection:
        return connection.execute(
            "SELECT id,sku,name,category,quantity,reorder_level,unit_price,updated_at FROM products ORDER BY id"
        ).fetchall()


def create_product(item):
    initialize()
    with connect() as connection:
        return connection.execute(
            """INSERT INTO products(sku,name,category,quantity,reorder_level,unit_price)
               VALUES (%s,%s,%s,%s,%s,%s)
               RETURNING id,sku,name,category,quantity,reorder_level,unit_price,updated_at""",
            (item.sku, item.name, item.category, item.quantity, item.reorder_level, item.unit_price),
        ).fetchone()


def update_product(product_id: int, item):
    initialize()
    with connect() as connection:
        return connection.execute(
            """UPDATE products SET name=%s,category=%s,quantity=%s,reorder_level=%s,unit_price=%s,updated_at=now()
               WHERE id=%s RETURNING id,sku,name,category,quantity,reorder_level,unit_price,updated_at""",
            (item.name, item.category, item.quantity, item.reorder_level, item.unit_price, product_id),
        ).fetchone()


def delete_product(product_id: int):
    initialize()
    with connect() as connection:
        return connection.execute("DELETE FROM products WHERE id=%s RETURNING id", (product_id,)).fetchone()
