"""The demo shop database: schema, deterministic data, the verifier user, and
the ways scripts/demo_db.py can deliberately break it.

The data satisfies src/checks/expectations.json; each break scenario makes
exactly one kind of integrity check fail, so the demo shows every check working.
"""
import random
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from checks import canary

COUNTS = {"customers": 60, "products": 25, "orders": 250, "order_items": 600}

SCHEMA = [
    "DROP TABLE IF EXISTS order_items, orders, products, customers, restorecheck_canary CASCADE",
    """CREATE TABLE customers (
        id integer PRIMARY KEY,
        name text NOT NULL,
        email text NOT NULL UNIQUE)""",
    """CREATE TABLE products (
        id integer PRIMARY KEY,
        name text NOT NULL,
        price numeric(10, 2) NOT NULL)""",
    """CREATE TABLE orders (
        id integer PRIMARY KEY,
        customer_id integer NOT NULL,
        created_at timestamptz NOT NULL,
        CONSTRAINT orders_customer_fk FOREIGN KEY (customer_id) REFERENCES customers (id))""",
    """CREATE TABLE order_items (
        id integer PRIMARY KEY,
        order_id integer NOT NULL,
        product_id integer NOT NULL,
        quantity integer NOT NULL,
        CONSTRAINT order_items_order_fk FOREIGN KEY (order_id) REFERENCES orders (id),
        CONSTRAINT order_items_product_fk FOREIGN KEY (product_id) REFERENCES products (id))""",
    f"""CREATE TABLE {canary.TABLE} (
        id integer PRIMARY KEY,
        payload text NOT NULL)""",
]

# Insertion order respects the foreign keys.
TABLE_ORDER = ["customers", "products", "orders", "order_items", canary.TABLE]

# Each scenario trips one check (see src/checks/).
BREAKS = {
    "missing-table": {
        "trips": "tables_present",
        "sql": ["DROP TABLE order_items"],
    },
    "truncated-table": {
        "trips": "row_counts",
        "sql": ["DELETE FROM order_items WHERE id > 100"],
    },
    "corrupt-data": {
        "trips": "canary_checksum",
        "sql": [f"UPDATE {canary.TABLE} SET payload = 'tampered' WHERE id = 42"],
    },
    "orphaned-rows": {
        "trips": "test_queries",
        "sql": [
            "ALTER TABLE order_items DROP CONSTRAINT order_items_order_fk",
            "DELETE FROM orders WHERE id IN (SELECT DISTINCT order_id FROM order_items LIMIT 5)",
        ],
    },
}

_ROLE_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")


def generate(seed=355):
    """Deterministic shop data (seeded with the course number, so every run matches)."""
    rng = random.Random(seed)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    n = COUNTS
    return {
        "customers": [
            (i, f"Customer {i:03d}", f"customer{i:03d}@example.com")
            for i in range(1, n["customers"] + 1)
        ],
        "products": [
            (i, f"Product {i:02d}", Decimal(f"{rng.uniform(1, 500):.2f}"))
            for i in range(1, n["products"] + 1)
        ],
        "orders": [
            (i, rng.randint(1, n["customers"]), start + timedelta(minutes=rng.randint(0, 400_000)))
            for i in range(1, n["orders"] + 1)
        ],
        "order_items": [
            (i, rng.randint(1, n["orders"]), rng.randint(1, n["products"]), rng.randint(1, 5))
            for i in range(1, n["order_items"] + 1)
        ],
        canary.TABLE: list(canary.ROWS),
    }


def insert_statements(table, rows, chunk=200):
    """Multi-row INSERTs (one round trip per chunk instead of per row)."""
    for i in range(0, len(rows), chunk):
        part = rows[i : i + chunk]
        width = len(part[0])
        row_placeholder = "(" + ", ".join(["%s"] * width) + ")"
        sql = f"INSERT INTO {table} VALUES " + ", ".join([row_placeholder] * len(part))
        yield sql, [value for row in part for value in row]


def verifier_user_sql(user, db_name):
    """The read-only user RestoreCheck's checker logs in as, via IAM authentication."""
    if not (_ROLE_NAME.match(user) and _ROLE_NAME.match(db_name)):
        raise ValueError("user and database names must be plain lowercase identifiers")
    return [
        f"""DO $$ BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{user}') THEN
                CREATE ROLE {user} LOGIN;
            END IF;
        END $$""",
        # rds_iam = this user can log in only with an IAM auth token, never a password.
        f"GRANT rds_iam TO {user}",
        f"GRANT CONNECT ON DATABASE {db_name} TO {user}",
        f"GRANT USAGE ON SCHEMA public TO {user}",
        f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {user}",
    ]
