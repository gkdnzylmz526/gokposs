# UI setup/cleanup for iteration 21: `python3 tests/ui_setup_it21.py setup|cleanup` (TEST_ invoices in florya; cleanup deletes TEST_ ids recorded in /tmp/it21_ids)
import json, sys
from datetime import date, timedelta
import requests
from conftest import get_token, ADMIN_EMAIL

BASE = open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split()[0].rstrip("/") + "/api"
s = requests.Session()
s.headers.update({"Authorization": f"Bearer {get_token(ADMIN_EMAIL)[1]}", "X-Restaurant": "florya-tasfirin"})
if sys.argv[1] == "setup":
    t = date.today()
    ids = []
    for sup, due, amt in (("TEST_Gecikmis", (t - timedelta(days=3)).isoformat(), 300), ("TEST_Yakin", (t + timedelta(days=2)).isoformat(), 200)):
        r = s.post(f"{BASE}/invoices", json={"supplier": sup, "date": t.isoformat(), "due_date": due, "amount": amt})
        ids.append(r.json()["id"])
    json.dump({"invoices": ids}, open("/tmp/it21_ids", "w"))
    print(ids)
else:
    for col in ("incomes", "invoices", "expenses"):
        for x in s.get(f"{BASE}/{col}").json():
            text = " ".join(str(x.get(k, "")) for k in ("note", "supplier", "category"))
            if "TEST_" in text and (x["id"] in json.load(open("/tmp/it21_ids")).get(col, []) or x.get("note", "").startswith("TEST_ui") or x.get("supplier", "").startswith("TEST_UI") or x.get("category", "").startswith("TEST_UI")):
                print(col, x["id"], s.delete(f"{BASE}/{col}/{x['id']}").status_code)
