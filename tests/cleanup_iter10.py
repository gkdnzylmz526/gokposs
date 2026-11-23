# Iteration 10 cleanup: delete only records created by this run (by id) + orphan movements/alerts not in pre-existing snapshot
import asyncio, json, os, requests
from dotenv import dotenv_values, load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
API = dotenv_values("/app/frontend/.env")["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
ids = json.load(open("/tmp/iter10_ids.json")); staff = json.load(open("/tmp/iter10_staff.json"))["staff"]
pre = json.load(open("/tmp/preexisting_ids.json"))
for e in ids["expenses"]: print("exp", requests.delete(f"{API}/expenses/{e}").status_code)
for i in ids["inventory"]: print("inv", requests.delete(f"{API}/inventory/{i}").status_code)
print("staff", requests.delete(f"{API}/staff/{staff}").status_code)
load_dotenv("/app/backend/.env")
db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
async def main():
    inv_ids = [x["id"] for x in await db.inventory.find({}, {"id": 1}).to_list(None)]
    staff_ids = [x["id"] for x in await db.staff.find({}, {"id": 1}).to_list(None)]
    for coll, field, alive in [("stock_movements", "inventory_id", inv_ids), ("price_alerts", "inventory_id", inv_ids), ("shifts", "staff_id", staff_ids)]:
        r = await db[coll].delete_many({field: {"$nin": alive}, "id": {"$nin": pre[coll]}})
        print(coll, "orphans removed", r.deleted_count)
    for c in sorted(await db.list_collection_names()): print(c, await db[c].count_documents({}))
asyncio.run(main())
