"""PostgreSQL access layer: connection pool, transactions, parameterised SQL.

Connection string comes from the DATABASE_URL environment variable, e.g.
  postgresql://postgres:postgres@localhost:5432/minidb
"""
import os
import re
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

_pool = None
SCHEMA_FILE = os.path.join(os.path.dirname(__file__), "..", "sql", "schema.sql")


class PGUnavailable(RuntimeError):
    pass


def get_pool():
    global _pool
    if _pool is None:
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise PGUnavailable("DATABASE_URL is not set")
        try:
            _pool = ThreadedConnectionPool(1, 10, url)
        except psycopg2.OperationalError as e:
            raise PGUnavailable(f"cannot connect to PostgreSQL: {e}".strip())
    return _pool


def close_pool():
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None


@contextmanager
def transaction():
    """BEGIN ... COMMIT; any exception -> ROLLBACK (all-or-nothing)."""
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def init_schema():
    with open(SCHEMA_FILE) as f, transaction() as cur:
        cur.execute(f.read())


# ------------------------------------------------------------------ CRUD
def create_customer(name, email, city):
    with transaction() as cur:
        cur.execute("INSERT INTO customers(name,email,city) VALUES (%s,%s,%s) RETURNING *", (name, email, city))
        return cur.fetchone()


def get_customer(cid):
    with transaction() as cur:
        cur.execute("SELECT * FROM customers WHERE id=%s", (cid,))
        return cur.fetchone()


def list_customers(limit=50, offset=0):
    with transaction() as cur:
        cur.execute("SELECT * FROM customers ORDER BY id LIMIT %s OFFSET %s", (limit, offset))
        return cur.fetchall()


def update_customer(cid, changes):
    allowed = {"name", "email", "city"}              # whitelist -> column names are never user text
    cols = [c for c in changes if c in allowed]
    if not cols:
        raise ValueError("nothing to update")
    sets = ", ".join(f"{c}=%s" for c in cols)
    with transaction() as cur:
        cur.execute(f"UPDATE customers SET {sets} WHERE id=%s RETURNING *", [changes[c] for c in cols] + [cid])
        return cur.fetchone()


def delete_customer(cid):
    with transaction() as cur:
        cur.execute("DELETE FROM customers WHERE id=%s", (cid,))
        return cur.rowcount == 1


def create_product(name, price, stock):
    with transaction() as cur:
        cur.execute("INSERT INTO products(name,price,stock) VALUES (%s,%s,%s) RETURNING *", (name, price, stock))
        return cur.fetchone()


def list_products():
    with transaction() as cur:
        cur.execute("SELECT * FROM products ORDER BY id")
        return cur.fetchall()


# ------------------------------------------------------------------ join
def orders_with_details(limit=50):
    """3-table JOIN: orders -> customers, orders -> products."""
    with transaction() as cur:
        cur.execute(
            """SELECT o.id AS order_id, c.name AS customer, p.name AS product,
                      o.quantity, (o.quantity * p.price) AS total, o.created_at
               FROM orders o
               JOIN customers c ON c.id = o.customer_id
               JOIN products  p ON p.id = o.product_id
               ORDER BY o.id LIMIT %s""", (limit,))
        return cur.fetchall()


# ------------------------------------------------------------------ transaction demo
class OutOfStock(Exception):
    pass


def place_order(customer_id, product_id, quantity):
    """Atomic: lock product row, check stock, decrement, insert order. Rolls back on failure."""
    with transaction() as cur:
        cur.execute("SELECT stock FROM products WHERE id=%s FOR UPDATE", (product_id,))  # row lock
        row = cur.fetchone()
        if row is None:
            raise LookupError("product not found")
        if row["stock"] < quantity:
            raise OutOfStock(f"only {row['stock']} in stock")
        cur.execute("UPDATE products SET stock = stock - %s WHERE id=%s", (quantity, product_id))
        cur.execute("INSERT INTO orders(customer_id,product_id,quantity) VALUES (%s,%s,%s) RETURNING *",
                    (customer_id, product_id, quantity))
        return cur.fetchone()


_ALLOWED = ("SELECT", "INSERT", "UPDATE", "DELETE")


def run_transaction(statements):
    """Run several parameterised statements as ONE transaction.

    statements: [{"sql": "...", "params": [...]}, ...]
    Guards (demo-grade, NOT a security boundary): one statement each, DML only, no ';',
    no comments. In production add authentication + a fixed set of named queries instead.
    """
    if not statements or len(statements) > 20:
        raise ValueError("send between 1 and 20 statements")
    for s in statements:
        sql = s["sql"].strip()
        if ";" in sql or "--" in sql or "/*" in sql:
            raise ValueError("only a single plain statement is allowed (no ';' or comments)")
        if not re.match(r"^(%s)\b" % "|".join(_ALLOWED), sql, re.I):
            raise ValueError("only SELECT / INSERT / UPDATE / DELETE are allowed")
    results = []
    with transaction() as cur:
        for s in statements:
            cur.execute(s["sql"], s.get("params") or [])
            results.append({"rowcount": cur.rowcount, "rows": cur.fetchall() if cur.description else []})
    return results
