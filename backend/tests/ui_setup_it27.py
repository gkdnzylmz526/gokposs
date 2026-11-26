# Iteration 27 UI helper: `create` makes tagged TEST_ products (ids -> /tmp/it27_ids), `cleanup` deletes them and clears the chef pick.
import json
import sys

import requests

sys.path.insert(0, "/app/backend/tests")
from clerk_helper import user_and_token  # noqa: E402

BASE = open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split()[0].rstrip("/") + "/api"
H = {"Authorization": f"Bearer {user_and_token('gokboss-admin+clerk_test@example.com')[1]}", "X-Restaurant": "florya-tasfirin"}

if sys.argv[1] == "create":
    ids = []
    for name, cat, tags in (("TEST_Falafel", "TEST_Vegan", ["vegan"]), ("TEST_Acili Durum", "TEST_Vegan", ["spicy"]), ("TEST_Baklava", "TEST_Tatli", ["nuts", "dairy"])):
        ids.append(requests.post(f"{BASE}/products", json={"name": name, "price": 120, "category": cat, "active": True, "tags": tags}, headers=H).json()["id"])
    json.dump(ids, open("/tmp/it27_ids", "w"))
    print(ids)
else:
    print("chef-pick", requests.delete(f"{BASE}/chef-pick", headers=H).status_code)
    for pid in json.load(open("/tmp/it27_ids")):
        print(pid, requests.delete(f"{BASE}/products/{pid}", headers=H).status_code)
