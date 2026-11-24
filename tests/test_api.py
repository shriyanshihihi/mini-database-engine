import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import minidb.api as api
    monkeypatch.setattr(api, "DB_DIR", str(tmp_path))
    with TestClient(api.app) as c:
        yield c


def test_engine_crud_and_join(client):
    r = client.post("/engine/tables", json={"name": "u", "columns": {"id": "int", "name": "text"}, "primary_key": "id"})
    assert r.status_code == 201
    client.post("/engine/tables", json={"name": "p", "columns": {"pid": "int", "uid": "int"}, "primary_key": "pid"})
    assert client.post("/engine/u/rows", json={"id": 1, "name": "A"}).status_code == 201
    assert client.post("/engine/u/rows", json={"id": 1, "name": "A"}).status_code == 409
    assert client.get("/engine/u/rows/1").json()["name"] == "A"
    assert client.get("/engine/u/rows/99").status_code == 404
    assert client.put("/engine/u/rows/1", json={"name": "B"}).json()["name"] == "B"
    client.post("/engine/p/rows", json={"pid": 10, "uid": 1})
    j = client.get("/engine/join", params=dict(left="p", right="u", left_col="uid", right_col="id")).json()
    assert j["strategy"] == "INDEX NESTED-LOOP JOIN" and j["rows"][0]["u.name"] == "B"
    assert "LOOKUP" in client.get("/engine/u/rows", params={"id": 1}).json()["plan"]
    assert client.delete("/engine/u/rows/1").status_code == 200
    assert client.post("/engine/u/rows", json={"id": "x", "name": "A"}).status_code == 400


PG = os.environ.get("DATABASE_URL")


@pytest.mark.skipif(not PG, reason="set DATABASE_URL to run PostgreSQL tests")
def test_pg_crud_join_and_transactions(client):
    assert client.post("/pg/init").status_code == 200
    import minidb.pg as pg
    with pg.transaction() as cur:
        cur.execute("TRUNCATE orders, products, customers RESTART IDENTITY CASCADE")
    cust = client.post("/pg/customers", json={"name": "Asha", "email": "a@x.com", "city": "Delhi"}).json()
    assert client.post("/pg/customers", json={"name": "Dup", "email": "a@x.com"}).status_code == 409
    prod = client.post("/pg/products", json={"name": "Pen", "price": 5, "stock": 3}).json()
    assert client.put(f"/pg/customers/{cust['id']}", json={"city": "Pune"}).json()["city"] == "Pune"
    # order succeeds and stock drops
    assert client.post("/pg/orders", json={"customer_id": cust["id"], "product_id": prod["id"], "quantity": 2}).status_code == 201
    # not enough stock -> 409 and NOTHING changes (rollback)
    assert client.post("/pg/orders", json={"customer_id": cust["id"], "product_id": prod["id"], "quantity": 5}).status_code == 409
    assert client.get("/pg/products").json()[0]["stock"] == 1
    d = client.get("/pg/orders/details").json()
    assert len(d) == 1 and d[0]["customer"] == "Asha" and float(d[0]["total"]) == 10.0
    # generic transaction: second statement violates CHECK -> whole thing rolls back
    bad = [{"sql": "UPDATE products SET stock = stock + 10 WHERE id=%s", "params": [prod["id"]]},
           {"sql": "UPDATE products SET stock = -1 WHERE id=%s", "params": [prod["id"]]}]
    assert client.post("/pg/transaction", json=bad).status_code == 400
    assert client.get("/pg/products").json()[0]["stock"] == 1
    # guards
    assert client.post("/pg/transaction", json=[{"sql": "DROP TABLE orders"}]).status_code == 400
    assert client.post("/pg/transaction", json=[{"sql": "SELECT 1; DROP TABLE orders"}]).status_code == 400
    ok = client.post("/pg/transaction", json=[{"sql": "SELECT count(*) AS n FROM orders"}]).json()
    assert ok[0]["rows"][0]["n"] == 1
    assert client.delete(f"/pg/customers/{cust['id']}").status_code == 200   # cascades to orders
