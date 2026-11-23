import json, requests
from dotenv import dotenv_values
API = dotenv_values("/app/frontend/.env")["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
ids = {}
def c(coll, p):
    r = requests.post(f"{API}/{coll}", json=p); r.raise_for_status(); ids.setdefault(coll, []).append(r.json()["id"]); return r.json()
s = c("suppliers", {"name": "TEST_Kasap", "phone": "05000000000"})
c("suppliers", {"name": "TEST_Manav"})
inv = c("inventory", {"name": "TEST_Kıyma", "quantity": 5, "unit": "kg", "unit_cost": 600, "supplier": "TEST_Kasap", "minimum": 1})
inv2 = c("inventory", {"name": "TEST_Domates", "quantity": 5, "unit": "kg", "unit_cost": 20, "supplier": "TEST_Manav", "minimum": 1})
p = c("products", {"name": "TEST_Burger", "price": 250, "recipe": [{"inventory_id": inv["id"], "amount": 0.15}]})
p2 = c("products", {"name": "TEST_Salata", "price": 50, "cost": 30})
c("expenses", {"category": "TEST_Alış", "purchases": [{"inventory_id": inv["id"], "quantity": 2, "unit_price": 720}]})
c("expenses", {"category": "TEST_Alış", "amount": 300, "supplier": "TEST_Manav"})
st = c("staff", {"name": "TEST_Ayşe", "shift": "10:00 – 18:00", "task": "Kasa", "status": "Aktif"})
print(json.dumps(ids))
json.dump(ids, open("/tmp/iter9_ids.json", "w"))
