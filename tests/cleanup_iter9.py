import json, os, requests
from dotenv import dotenv_values
from pymongo import MongoClient
API = dotenv_values("/app/frontend/.env")["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
ids = json.load(open("/tmp/iter9_ids.json"))
# UI-created expense
ids["expenses"] += [e["id"] for e in requests.get(f"{API}/expenses").json() if e.get("category") == "TEST_UI_Gider"]
inv_ids = list(ids.get("inventory", []))
for coll in ["expenses", "products", "inventory", "staff", "suppliers"]:
    for i in ids.get(coll, []):
        print(coll, i, requests.delete(f"{API}/{coll}/{i}").status_code)
env = dotenv_values("/app/backend/.env")
db = MongoClient(env["MONGO_URL"])[env["DB_NAME"]]
live = {i["id"] for i in db.inventory.find({}, {"id": 1})}
staff = {s["id"] for s in db.staff.find({}, {"id": 1})}
# orphaned test records only (inventory deleted, TEST_ name)
q = {"inventory_id": {"$nin": list(live)}, "inventory_name": {"$regex": "^TEST_"}}
print("stock_movements removed:", db.stock_movements.delete_many(q).deleted_count)
print("price_alerts removed:", db.price_alerts.delete_many(q).deleted_count)
print("orphan shifts removed:", db.shifts.delete_many({"staff_id": {"$nin": list(staff)}}).deleted_count)
for c in ["sales", "expenses", "inventory", "staff", "products", "suppliers", "shifts", "price_alerts", "stock_movements", "cash", "cron_runs"]:
    print(c, db[c].count_documents({}), [d.get("name") or d.get("category") or d.get("inventory_name") or d.get("staff_id") for d in db[c].find({}, {"_id": 0}).limit(5)])
