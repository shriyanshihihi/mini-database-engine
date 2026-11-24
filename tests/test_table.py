import pytest
from minidb import Database, DuplicateKeyError, SchemaError


@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path))
    c = d.create_table("customers", {"id": "int", "name": "text", "city": "text"}, "id")
    o = d.create_table("orders", {"oid": "int", "cid": "int", "amount": "float"}, "oid")
    for i in range(1, 6):
        c.insert({"id": i, "name": f"C{i}", "city": "Delhi" if i % 2 else "Pune"})
    for i in range(1, 9):
        o.insert({"oid": i, "cid": (i % 6) + 1, "amount": i * 10})   # cid 6 has no customer
    return d, str(tmp_path)


def test_crud(db):
    d, _ = db; c = d.table("customers")
    assert c.get(3)["name"] == "C3"
    with pytest.raises(DuplicateKeyError):
        c.insert({"id": 3, "name": "x", "city": "y"})
    assert c.update(3, {"name": "New"})["name"] == "New" and c.get(3)["name"] == "New"
    assert c.delete(3) and c.get(3) is None and not c.delete(3)
    assert c.count() == 4


def test_validation(db):
    d, _ = db; c = d.table("customers")
    with pytest.raises(SchemaError): c.insert({"id": "abc", "name": "x", "city": "y"})
    with pytest.raises(SchemaError): c.insert({"id": 9, "name": "x"})
    with pytest.raises(SchemaError): c.update(1, {"id": 2})


def test_select_plans(db):
    d, _ = db; c = d.table("customers")
    assert "LOOKUP" in c.explain({"id": 1}) and "RANGE" in c.explain(pk_min=1) and "FULL" in c.explain({"city": "x"})
    assert [r["id"] for r in c.select(pk_min=2, pk_max=4)] == [2, 3, 4]
    assert {r["id"] for r in c.select({"city": "Delhi"})} == {1, 3, 5}


def test_persistence_and_index_rebuild(db):
    d, path = db
    d.table("customers").delete(2); d.table("customers").update(1, {"name": "Z"}); d.close()
    d2 = Database(path); c = d2.table("customers")
    assert c.get(1)["name"] == "Z" and c.get(2) is None and c.count() == 4
    d2.close()
    import os; os.remove(os.path.join(path, "customers.idx"))      # lose the index snapshot
    d3 = Database(path); c = d3.table("customers")                  # -> rebuilt from the data file
    assert c.get(1)["name"] == "Z" and c.get(2) is None and c.count() == 4


def test_compact_shrinks_file(db):
    d, _ = db; c = d.table("orders")
    for i in range(1, 8): c.delete(i)
    before = c.heap.size(); c.compact()
    assert c.heap.size() < before and c.count() == 1 and c.get(8)["amount"] == 80


def test_joins(db):
    d, _ = db
    rows, strat = d.join("orders", "customers", "cid", "id")           # right col is PK -> index join
    assert strat == "INDEX NESTED-LOOP JOIN" and len(rows) == 7        # order with cid 6 dropped
    rows, _ = d.join("orders", "customers", "cid", "id", kind="left")
    assert len(rows) == 8 and any(r["customers.name"] is None for r in rows)
    rows, strat = d.join("customers", "orders", "id", "cid")           # right col not PK -> hash join
    assert strat == "HASH JOIN"
