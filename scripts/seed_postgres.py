"""Create the PostgreSQL schema and load synthetic demo rows. Needs DATABASE_URL."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from minidb import pg
pg.init_schema()
for n, e, c in [("Asha Rao", "asha@example.com", "Delhi"), ("Vikram Shah", "vikram@example.com", "Mumbai")]:
    try: pg.create_customer(n, e, c)
    except Exception as ex: print("skip customer:", ex.__class__.__name__)
if not pg.list_products():
    for n, p, s in [("Notebook", 120.5, 50), ("Backpack", 1450, 10)]: pg.create_product(n, p, s)
print("PostgreSQL ready: demo data (synthetic) loaded")
