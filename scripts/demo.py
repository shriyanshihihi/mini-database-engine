"""2-minute demo of the engine (no PostgreSQL needed). Uses SYNTHETIC sample data from /data."""
import csv, os, sys, tempfile
ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
from minidb import Database, DuplicateKeyError

db = Database(tempfile.mkdtemp(prefix="minidb_demo_"))
cust = db.create_table("customers", {"id": "int", "name": "text", "city": "text"}, "id")
orders = db.create_table("orders", {"order_id": "int", "customer_id": "int", "item": "text", "amount": "float"}, "order_id")
for r in csv.DictReader(open(os.path.join(ROOT, "data", "sample_customers.csv"))): cust.insert(r)
for r in csv.DictReader(open(os.path.join(ROOT, "data", "sample_orders.csv"))): orders.insert(r)

def show(title, rows):
    print(f"\n--- {title}")
    for r in rows: print("   ", r)

print("Loaded", cust.count(), "customers and", orders.count(), "orders (synthetic demo data)")
print("\nPLAN for id=3        :", cust.explain({"id": 3}))
print("PLAN for city=Pune   :", cust.explain({"city": "Pune"}))
print("PLAN for id 2..4     :", cust.explain(pk_min=2, pk_max=4))
show("SELECT * FROM customers WHERE id = 3", cust.select({"id": 3}))
show("SELECT ... WHERE id BETWEEN 2 AND 4", cust.select(pk_min=2, pk_max=4))
show("SELECT ... WHERE city = 'Pune'  (full scan)", cust.select({"city": "Pune"}))
print("\n--- UPDATE customers SET city='Goa' WHERE id=3  ->", cust.update(3, {"city": "Goa"}))
print("--- DELETE customers WHERE id=5                 ->", cust.delete(5))
try: cust.insert({"id": 1, "name": "Dup", "city": "X"})
except DuplicateKeyError as e: print("--- duplicate PK rejected:", e.args[0])
rows, strat = db.join("orders", "customers", "customer_id", "id")
show(f"JOIN orders x customers  [{strat}]", rows)
rows, strat = db.join("orders", "customers", "customer_id", "id", kind="left")
print(f"\nLEFT JOIN keeps orders whose customer was deleted: {sum(r['customers.name'] is None for r in rows)} such row(s)")
db.close()
