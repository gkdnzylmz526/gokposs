# Iteration 26 UI helper: `create` makes TEST products in 2 categories (ids -> /tmp/it26_ids), `cleanup` deletes them and restores menu order state.
import json
import sys

import pymongo
import requests

sys.path.insert(0, "/app/backend/tests")
from clerk_helper import user_and_token  # noqa: E402

BASE = open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split()[0].rstrip("/") + "/api"
H = {"Authorization": f"Bearer {user_and_token('gokboss-admin+clerk_test@example.com')[1]}", "X-Restaurant": "florya-tasfirin"}

if sys.argv[1] == "create":
    ids = []
    for name, cat in (("TEST_UI_A1", "TEST_UICatA"), ("TEST_UI_A2", "TEST_UICatA"), ("TEST_UI_B1", "TEST_UICatB")):
        ids.append(requests.post(f"{BASE}/products", json={"name": name, "price": 15, "category": cat, "active": True}, headers=H).json()["id"])
    json.dump(ids, open("/tmp/it26_ids", "w"))
    print(ids)
else:
    for pid in json.load(open("/tmp/it26_ids")):
        print(pid, requests.delete(f"{BASE}/products/{pid}", headers=H).status_code)
    env = dict(l.split("=", 1) for l in open("/app/backend/.env").read().splitlines() if "=" in l)
    c = pymongo.MongoClient(env["MONGO_URL"].strip('"'))[env["DB_NAME"].strip('"')]
    print(c.settings.delete_one({"id": "menu_order"}).deleted_count, c.products.update_one({"name": "adana"}, {"$unset": {"sort_order": ""}}).modified_count)
    print(requests.get(f"{BASE}/public/menu", headers={}).json())
