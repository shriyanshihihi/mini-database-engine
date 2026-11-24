"""FastAPI REST layer.

  /engine/...  -> our own file-based engine with the B-Tree index
  /pg/...      -> PostgreSQL (CRUD, joins, transactions)
Run:  uvicorn minidb.api:app --reload      then open http://127.0.0.1:8000/docs
"""
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import psycopg2
from fastapi import Body, FastAPI, HTTPException, Request
from pydantic import BaseModel

from . import pg
from .table import Database, DuplicateKeyError, SchemaError

DB_DIR = os.environ.get("MINIDB_DIR", os.path.join(os.path.dirname(__file__), "..", "data", "db"))
db: Optional[Database] = None


@asynccontextmanager
async def lifespan(app):
    global db
    db = Database(DB_DIR)
    yield
    db.close()
    pg.close_pool()


app = FastAPI(title="Mini Database Engine API", version="1.0", lifespan=lifespan)


def _table(name):
    try:
        return db.table(name)
    except KeyError as e:
        raise HTTPException(404, str(e).strip("'\""))


# =========================================================== engine routes
class TableSpec(BaseModel):
    name: str
    columns: Dict[str, str]
    primary_key: str


@app.get("/engine/tables")
def list_tables():
    return {n: {"columns": t.columns, "primary_key": t.primary_key, "rows": t.count()} for n, t in db.tables.items()}


@app.post("/engine/tables", status_code=201)
def create_table(spec: TableSpec):
    try:
        t = db.create_table(spec.name, spec.columns, spec.primary_key)
    except SchemaError as e:
        raise HTTPException(400, str(e))
    return {"created": t.name}


@app.get("/engine/join")          # declared before /engine/{table}/... so "join" is not read as a table name
def join(left: str, right: str, left_col: str, right_col: str, kind: str = "inner", limit: int = 100):
    try:
        rows, strategy = db.join(left, right, left_col, right_col, kind, limit)
    except KeyError as e:
        raise HTTPException(404, str(e).strip("'\""))
    except SchemaError as e:
        raise HTTPException(400, str(e))
    return {"strategy": strategy, "count": len(rows), "rows": rows}


@app.post("/engine/{table}/rows", status_code=201)
def insert_row(table: str, row: Dict[str, Any] = Body(...)):
    try:
        return _table(table).insert(row)
    except DuplicateKeyError as e:
        raise HTTPException(409, str(e.args[0]))
    except SchemaError as e:
        raise HTTPException(400, str(e))


@app.get("/engine/{table}/rows/{pk}")
def get_row(table: str, pk: str):
    try:
        row = _table(table).get(pk)
    except SchemaError as e:
        raise HTTPException(400, str(e))
    if row is None:
        raise HTTPException(404, "row not found")
    return row


@app.get("/engine/{table}/rows")
def select_rows(table: str, request: Request, pk_min: Optional[str] = None, pk_max: Optional[str] = None,
                limit: int = 100):
    """Any other query parameter col=value is an equality filter, e.g. ?city=Delhi"""
    t = _table(table)
    where = {k: v for k, v in request.query_params.items() if k not in ("pk_min", "pk_max", "limit")}
    try:
        plan = t.explain(where, pk_min, pk_max)
        rows = t.select(where, pk_min, pk_max, limit)
    except SchemaError as e:
        raise HTTPException(400, str(e))
    return {"plan": plan, "count": len(rows), "rows": rows}


@app.put("/engine/{table}/rows/{pk}")
def update_row(table: str, pk: str, changes: Dict[str, Any] = Body(...)):
    try:
        row = _table(table).update(pk, changes)
    except SchemaError as e:
        raise HTTPException(400, str(e))
    if row is None:
        raise HTTPException(404, "row not found")
    return row


@app.delete("/engine/{table}/rows/{pk}")
def delete_row(table: str, pk: str):
    try:
        ok = _table(table).delete(pk)
    except SchemaError as e:
        raise HTTPException(400, str(e))
    if not ok:
        raise HTTPException(404, "row not found")
    return {"deleted": pk}


@app.post("/engine/{table}/compact")
def compact(table: str):
    _table(table).compact()
    return {"compacted": table}


# =========================================================== PostgreSQL routes
def _pg(fn, *a, **kw):
    """Run a pg call and translate database errors into HTTP errors."""
    try:
        return fn(*a, **kw)
    except pg.PGUnavailable as e:
        raise HTTPException(503, str(e))
    except psycopg2.errors.UniqueViolation:
        raise HTTPException(409, "unique constraint violated")
    except (psycopg2.errors.ForeignKeyViolation, psycopg2.errors.CheckViolation, psycopg2.errors.NotNullViolation) as e:
        raise HTTPException(400, e.pgerror.splitlines()[0] if e.pgerror else "constraint violated")
    except psycopg2.Error as e:
        raise HTTPException(400, (e.pgerror or str(e)).splitlines()[0])
    except ValueError as e:
        raise HTTPException(400, str(e))


class CustomerIn(BaseModel):
    name: str
    email: str
    city: Optional[str] = None


class ProductIn(BaseModel):
    name: str
    price: float
    stock: int


class OrderIn(BaseModel):
    customer_id: int
    product_id: int
    quantity: int


class Statement(BaseModel):
    sql: str
    params: List[Any] = []


@app.post("/pg/init")
def pg_init():
    _pg(pg.init_schema)
    return {"schema": "ready"}


@app.post("/pg/customers", status_code=201)
def pg_create_customer(c: CustomerIn):
    return _pg(pg.create_customer, c.name, c.email, c.city)


@app.get("/pg/customers")
def pg_list_customers(limit: int = 50, offset: int = 0):
    return _pg(pg.list_customers, min(limit, 500), offset)


@app.get("/pg/customers/{cid}")
def pg_get_customer(cid: int):
    row = _pg(pg.get_customer, cid)
    if not row:
        raise HTTPException(404, "customer not found")
    return row


@app.put("/pg/customers/{cid}")
def pg_update_customer(cid: int, changes: Dict[str, Any] = Body(...)):
    row = _pg(pg.update_customer, cid, changes)
    if not row:
        raise HTTPException(404, "customer not found")
    return row


@app.delete("/pg/customers/{cid}")
def pg_delete_customer(cid: int):
    if not _pg(pg.delete_customer, cid):
        raise HTTPException(404, "customer not found")
    return {"deleted": cid}


@app.post("/pg/products", status_code=201)
def pg_create_product(p: ProductIn):
    return _pg(pg.create_product, p.name, p.price, p.stock)


@app.get("/pg/products")
def pg_list_products():
    return _pg(pg.list_products)


@app.post("/pg/orders", status_code=201)
def pg_place_order(o: OrderIn):
    try:
        return _pg(pg.place_order, o.customer_id, o.product_id, o.quantity)
    except pg.OutOfStock as e:
        raise HTTPException(409, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))


@app.get("/pg/orders/details")
def pg_orders_join(limit: int = 50):
    return _pg(pg.orders_with_details, min(limit, 500))


@app.post("/pg/transaction")
def pg_transaction(statements: List[Statement]):
    return _pg(pg.run_transaction, [s.model_dump() for s in statements])
