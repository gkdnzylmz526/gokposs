# Iteration 10 UI seed: TEST_ ingredients with priced purchases from 2 suppliers + one empty ingredient
import json, time, requests
from dotenv import dotenv_values
API = dotenv_values("/app/frontend/.env")["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
ids = {"inventory": [], "expenses": []}
def post(c, p):
    r = requests.post(f"{API}/{c}", json=p); r.raise_for_status(); ids[c].append(r.json()["id"]); return r.json()
empty = post("inventory", {"name": "TEST_UI_Bos", "quantity": 1, "unit": "kg"})
inv = post("inventory", {"name": "TEST_UI_Kiyma", "quantity": 0, "unit": "kg", "supplier": "TEST_Kasap_A"})
for sup, price in [("TEST_Kasap_A", 500), ("TEST_Kasap_A", 540), ("TEST_Kasap_B", 520)]:
    post("expenses", {"category": "TEST", "supplier": sup, "purchases": [{"inventory_id": inv["id"], "quantity": 2, "unit_price": price}]}); time.sleep(0.05)
json.dump(ids, open("/tmp/iter10_ids.json", "w"))
print(ids, inv["id"], empty["id"])
