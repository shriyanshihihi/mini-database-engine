# Mini Database Engine

A small, readable database engine built to learn (and explain) how databases work internally.

* **File-based storage engine** - `INSERT`, `SELECT`, `UPDATE`, `DELETE` on an append-only data file.
* **B-Tree index** on the primary key - point lookups go from O(N) (scan) to O(log N) (tree search).
* **FastAPI REST API** with two paths: our own engine (`/engine/*`) and **PostgreSQL** (`/pg/*`) for CRUD,
  table joins and transactional SQL execution.

> All data in `data/` and `sample_output/` is **synthetic demo data**. Benchmark numbers in
> `sample_output/benchmark.txt` were produced by running `scripts/benchmark.py` on one machine; re-run it for your own.
> This is a learning prototype, not production software (see "Limitations").

![architecture](docs/architecture.png)

## Setup
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run (no PostgreSQL needed)
```bash
python scripts/demo.py            # 2-minute demo: CRUD, query plans, joins
python scripts/benchmark.py       # B-Tree vs linear scan on 100,000 synthetic rows
python -m pytest -q               # unit + API tests
uvicorn minidb.api:app --reload   # REST API, docs at http://127.0.0.1:8000/docs
```

## Run with PostgreSQL (optional, enables /pg/* routes)
```bash
createdb minidb
export DATABASE_URL=postgresql://USER:PASSWORD@localhost:5432/minidb
python scripts/seed_postgres.py
uvicorn minidb.api:app --reload
python -m pytest -q               # now also runs the PostgreSQL tests
```

## Project layout
| Path | What it is |
|---|---|
| `minidb/btree.py` | B-Tree (insert, search, delete with borrow/merge, range scan, invariant checker) |
| `minidb/storage.py` | `HeapFile`: record format `[flag][length][payload]`, append, read at offset, tombstone, scan |
| `minidb/table.py` | `Table` (schema, CRUD, query planner), `Database` (catalog, joins), index snapshot + rebuild |
| `minidb/pg.py` | PostgreSQL pool, `transaction()` context manager, CRUD, JOIN query, atomic `place_order`, guarded multi-statement transaction |
| `minidb/api.py` | FastAPI routes for both paths |
| `sql/schema.sql` | PostgreSQL schema (customers, products, orders) |
| `scripts/` | `demo.py`, `benchmark.py`, `seed_postgres.py` |
| `tests/` | B-Tree vs dict model test, table tests, API tests (PostgreSQL tests need `DATABASE_URL`) |
| `docs/` | diagrams (`python docs/make_diagrams.py` regenerates them) |

## How it works in one paragraph
Each row is stored as a record in `<table>.dat`. The B-Tree maps **primary key -> byte offset** of the newest version of
that row. `get(pk)` searches the tree (a few node visits) and does one seek+read. Updates append a new version and
tombstone the old one; deletes tombstone and remove the key from the tree. The tree lives in memory; on close it is
saved to `<table>.idx` and on open it is reloaded (or rebuilt by scanning the `.dat` file if missing/stale).

## Example API calls
```bash
curl -X POST localhost:8000/engine/tables -H 'content-type: application/json' \
  -d '{"name":"users","columns":{"id":"int","name":"text"},"primary_key":"id"}'
curl -X POST localhost:8000/engine/users/rows -H 'content-type: application/json' -d '{"id":1,"name":"Asha"}'
curl localhost:8000/engine/users/rows/1
curl "localhost:8000/engine/users/rows?pk_min=1&pk_max=10"     # response includes the query plan
curl "localhost:8000/engine/join?left=orders&right=users&left_col=user_id&right_col=id"
```

## Limitations (honest list)
* B-Tree is **in memory** with a snapshot file; it is not a paged on-disk B-Tree and is not crash-safe mid-write.
* No write-ahead log / transactions in our engine (PostgreSQL path has real ACID transactions).
* Only the primary key is indexed; other filters do full scans. No SQL parser, no query optimiser beyond simple rules.
* One process; a lock serialises access per table. Updates leave tombstones until `compact()`.
* `/pg/transaction` runs caller-supplied SQL: it is guarded for the demo but needs authentication before real use.
