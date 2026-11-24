"""Tables, the Database catalog, and joins.

A Table = HeapFile (rows on disk) + BTree (primary-key index in memory,
snapshotted to <table>.idx on close, rebuilt from the data file if missing/stale).
"""
import json
import os
import threading

from .btree import BTree
from .storage import HeapFile

TYPES = {"int": int, "float": float, "text": str}


class SchemaError(ValueError):
    pass


class DuplicateKeyError(KeyError):
    pass


class Table:
    def __init__(self, directory, name, columns=None, primary_key=None, btree_t=32, sync=False):
        self.name = name
        self._lock = threading.RLock()        # API threads share one Table
        self._schema_path = os.path.join(directory, f"{name}.schema.json")
        self._data_path = os.path.join(directory, f"{name}.dat")
        self._idx_path = os.path.join(directory, f"{name}.idx")
        self.btree_t = btree_t
        if columns is not None:
            self._init_schema(columns, primary_key)
        else:
            with open(self._schema_path) as f:
                s = json.load(f)
            self.columns, self.primary_key = s["columns"], s["primary_key"]
        self.col_names = list(self.columns)
        self.heap = HeapFile(self._data_path, sync=sync)
        self.index = BTree(t=btree_t)
        self._load_or_rebuild_index()

    # ------------------------------------------------------------ schema
    def _init_schema(self, columns, primary_key):
        for c, t in columns.items():
            if t not in TYPES:
                raise SchemaError(f"unknown type {t!r} for column {c!r}; use int/float/text")
        if primary_key not in columns:
            raise SchemaError("primary_key must be one of the columns")
        if columns[primary_key] not in ("int", "text"):
            raise SchemaError("primary key must be int or text")
        self.columns, self.primary_key = dict(columns), primary_key
        with open(self._schema_path, "w") as f:
            json.dump({"columns": self.columns, "primary_key": primary_key}, f)

    def coerce(self, col, value):
        if col not in self.columns:
            raise SchemaError(f"unknown column {col!r}")
        try:
            return TYPES[self.columns[col]](value)
        except (TypeError, ValueError):
            raise SchemaError(f"column {col!r} expects {self.columns[col]}, got {value!r}")

    def _validate_row(self, row):
        extra = set(row) - set(self.columns)
        if extra:
            raise SchemaError(f"unknown columns: {sorted(extra)}")
        missing = [c for c in self.columns if c not in row]
        if missing:
            raise SchemaError(f"missing columns: {missing}")
        return {c: self.coerce(c, row[c]) for c in self.col_names}

    # row <-> bytes (compact: JSON array in schema order)
    def _encode(self, row):
        return json.dumps([row[c] for c in self.col_names], separators=(",", ":")).encode()

    def _decode(self, payload):
        return dict(zip(self.col_names, json.loads(payload)))

    # ------------------------------------------------------------ index persistence
    def _load_or_rebuild_index(self):
        """Fast path: load snapshot if it matches the data file size. Else full scan."""
        size = self.heap.size()
        if os.path.exists(self._idx_path):
            try:
                with open(self._idx_path) as f:
                    snap = json.load(f)
                if snap["heap_size"] == size:
                    for k, off in snap["items"]:
                        self.index.insert(k, off)
                    return
            except (ValueError, KeyError):
                pass
        self.rebuild_index()

    def rebuild_index(self):
        with self._lock:
            self.index = BTree(t=self.btree_t)
            pk_pos = self.col_names.index(self.primary_key)
            for off, payload in self.heap.scan():
                self.index.insert(json.loads(payload)[pk_pos], off)

    def _save_index(self):
        tmp = self._idx_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"heap_size": self.heap.size(), "items": [[k, v] for k, v in self.index.items()]}, f)
        os.replace(tmp, self._idx_path)       # atomic swap

    # ------------------------------------------------------------ CRUD
    def insert(self, row):
        with self._lock:
            row = self._validate_row(row)
            pk = row[self.primary_key]
            if self.index.search(pk) is not None:
                raise DuplicateKeyError(f"{self.name}: primary key {pk!r} already exists")
            self.index.insert(pk, self.heap.append(self._encode(row)))
            return row

    def get(self, pk):
        """Point lookup: B-Tree search O(log N) + one disk read."""
        with self._lock:
            off = self.index.search(self.coerce(self.primary_key, pk))
            return None if off is None else self._decode(self.heap.read(off))

    def update(self, pk, changes):
        with self._lock:
            pk = self.coerce(self.primary_key, pk)
            off = self.index.search(pk)
            if off is None:
                return None
            if self.primary_key in changes and self.coerce(self.primary_key, changes[self.primary_key]) != pk:
                raise SchemaError("primary key cannot be changed; delete and re-insert instead")
            row = self._decode(self.heap.read(off))
            row.update(changes)
            row = self._validate_row(row)
            new_off = self.heap.append(self._encode(row))   # write new version first ...
            self.heap.tombstone(off)                       # ... then retire the old one
            self.index.insert(pk, new_off)                 # same key -> value replaced
            return row

    def delete(self, pk):
        with self._lock:
            pk = self.coerce(self.primary_key, pk)
            off = self.index.search(pk)
            if off is None:
                return False
            self.heap.tombstone(off)
            self.index.delete(pk)
            return True

    # ------------------------------------------------------------ queries
    def explain(self, where=None, pk_min=None, pk_max=None):
        where = where or {}
        if self.primary_key in where:
            return "INDEX LOOKUP (B-Tree point search, O(log N))"
        if pk_min is not None or pk_max is not None:
            return "INDEX RANGE SCAN (B-Tree in-order walk, O(log N + k))"
        return "FULL TABLE SCAN (read every record, O(N))"

    def select(self, where=None, pk_min=None, pk_max=None, limit=None):
        """where = {col: value} equality filters (AND). Uses the index whenever the PK is involved."""
        with self._lock:
            where = {c: self.coerce(c, v) for c, v in (where or {}).items()}
            lo = None if pk_min is None else self.coerce(self.primary_key, pk_min)
            hi = None if pk_max is None else self.coerce(self.primary_key, pk_max)

            def rows():
                if self.primary_key in where:
                    r = self.get(where[self.primary_key])
                    if r is not None:
                        yield r
                elif lo is not None or hi is not None:
                    for _, off in self.index.range(lo, hi):
                        yield self._decode(self.heap.read(off))
                else:
                    for _, payload in self.heap.scan():
                        yield self._decode(payload)

            out = []
            for r in rows():
                if all(r[c] == v for c, v in where.items()) and \
                   (lo is None or r[self.primary_key] >= lo) and (hi is None or r[self.primary_key] <= hi):
                    out.append(r)
                    if limit is not None and len(out) >= limit:
                        break
            return out

    def scan_find(self, pk):
        """Deliberately index-free lookup (linear scan) - used by the benchmark baseline."""
        pk_pos = self.col_names.index(self.primary_key)
        for _, payload in self.heap.scan():
            r = json.loads(payload)
            if r[pk_pos] == pk:
                return dict(zip(self.col_names, r))
        return None

    def count(self):
        return len(self.index)

    # ------------------------------------------------------------ maintenance
    def compact(self):
        """Rewrite the data file with only live rows (reclaims tombstone space)."""
        with self._lock:
            live = [self.heap.read(off) for _, off in self.index.items()]
            self.heap.close()
            os.remove(self._data_path)
            self.heap = HeapFile(self._data_path, sync=self.heap.sync)
            self.index = BTree(t=self.btree_t)
            pk_pos = self.col_names.index(self.primary_key)
            for payload in live:
                self.index.insert(json.loads(payload)[pk_pos], self.heap.append(payload))

    def close(self):
        with self._lock:
            self._save_index()
            self.heap.close()


class Database:
    """A directory of tables."""

    def __init__(self, directory, btree_t=32, sync=False):
        self.dir, self.btree_t, self.sync = directory, btree_t, sync
        os.makedirs(directory, exist_ok=True)
        self.tables = {}
        for fn in sorted(os.listdir(directory)):
            if fn.endswith(".schema.json"):
                name = fn[: -len(".schema.json")]
                self.tables[name] = Table(directory, name, btree_t=btree_t, sync=sync)

    def create_table(self, name, columns, primary_key):
        if not name.isidentifier():
            raise SchemaError("table name must be a simple identifier")
        if name in self.tables:
            raise SchemaError(f"table {name!r} already exists")
        self.tables[name] = Table(self.dir, name, columns, primary_key, self.btree_t, self.sync)
        return self.tables[name]

    def table(self, name):
        if name not in self.tables:
            raise KeyError(f"no such table: {name}")
        return self.tables[name]

    def join(self, left, right, left_col, right_col, kind="inner", limit=None):
        """Join two tables on left.left_col = right.right_col.

        * right_col is right's primary key -> INDEX NESTED-LOOP JOIN: one B-Tree probe per left row,
          O(L log R).
        * otherwise -> HASH JOIN: build dict on right in one scan, probe with left, O(L + R).
        Returns (rows, strategy). Output keys are prefixed "table.column".
        """
        if kind not in ("inner", "left"):
            raise SchemaError("kind must be 'inner' or 'left'")
        L, R = self.table(left), self.table(right)
        for t, c in ((L, left_col), (R, right_col)):
            if c not in t.columns:
                raise SchemaError(f"unknown column {c!r} in table {t.name!r}")
        null_right = {f"{right}.{c}": None for c in R.col_names}
        use_index = right_col == R.primary_key
        if use_index:
            strategy = "INDEX NESTED-LOOP JOIN"
            probe = lambda v: [R.get(v)] if R.get(v) is not None else []
        else:
            strategy = "HASH JOIN"
            buckets = {}
            for r in R.select():
                buckets.setdefault(r[right_col], []).append(r)
            probe = lambda v: buckets.get(v, [])
        out = []
        for lrow in L.select():
            matches = probe(lrow[left_col])
            if not matches and kind == "left":
                out.append({**{f"{left}.{c}": v for c, v in lrow.items()}, **null_right})
            for rrow in matches:
                out.append({**{f"{left}.{c}": v for c, v in lrow.items()},
                            **{f"{right}.{c}": v for c, v in rrow.items()}})
            if limit is not None and len(out) >= limit:
                out = out[:limit]
                break
        return out, strategy

    def close(self):
        for t in self.tables.values():
            t.close()
