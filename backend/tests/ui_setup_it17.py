# UI setup for iteration 17 (Etiler Marmaris): TEST_ inventory/product/staff + member assigned; prints ids + tickets.
# Usage: python3 tests/ui_setup_it17.py            -> setup
#        python3 tests/ui_setup_it17.py cleanup '<json printed by setup>'
import sys, json, urllib.parse, requests
from clerk_helper import user_and_token, bapi
API = open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split()[0].rstrip("/") + "/api"
_, tok = user_and_token("gokboss-admin+clerk_test@example.com")
ET = "etiler-marmaris"
h = {"Authorization": f"Bearer {tok}", "X-Restaurant": ET}
member_uid, _ = user_and_token("gokboss-member+clerk_test@example.com")
member_uid = member_uid["id"]
if len(sys.argv) > 1 and sys.argv[1] == "cleanup":
    d = json.loads(sys.argv[2])
    prods = set(d["prods"]) | {p["id"] for p in requests.get(f"{API}/products", headers=h).json() if p["name"].startswith("TEST_UI17")}
    for rid in ("florya-tasfirin", ET, "durumtir"):
        hh = {**h, "X-Restaurant": rid}
        for s in requests.get(f"{API}/sales", headers=hh).json():
            if s.get("product_id") in prods:
                print("del sale", requests.delete(f"{API}/sales/{s['id']}", headers=hh).status_code)
        for coll in ("tips", "attendance"):
            for t in requests.get(f"{API}/{coll}", headers=hh).json():
                if t.get("staff_id") == d["staff"] or "TEST_UI17" in t.get("note", ""):
                    print("del", coll, requests.delete(f"{API}/{coll}/{t['id']}", headers=hh).status_code)
        for t in requests.get(f"{API}/tables", headers=hh).json():
            if t["name"].startswith("TEST_UI17"):
                print("del table", requests.delete(f"{API}/tables/{t['id']}", headers=hh).status_code)
    for p in prods:
        print("del prod", requests.delete(f"{API}/products/{p}", headers=h).status_code)
    print("del inv", requests.delete(f"{API}/inventory/{d['inv']}", headers=h).status_code, "del staff", requests.delete(f"{API}/staff/{d['staff']}", headers=h).status_code)
    print("restore member", requests.patch(f"{API}/users/{member_uid}/assignment", json={"restaurant_id": "florya-tasfirin", "staff_id": ""}, headers=h).status_code)
    sys.exit()
inv = requests.post(f"{API}/inventory", json={"name": "TEST_UI17_Et", "quantity": 20, "unit": "kg", "minimum": 2, "unit_cost": 40}, headers=h).json()
prod = requests.post(f"{API}/products", json={"name": "TEST_UI17_Kebap", "category": "TEST", "price": 150, "recipe": [{"inventory_id": inv["id"], "amount": 0.25}]}, headers=h).json()
norec = requests.post(f"{API}/products", json={"name": "TEST_UI17_Ayran", "category": "TEST", "price": 30}, headers=h).json()
staff = requests.post(f"{API}/staff", json={"name": "TEST_UI17_Garson", "task": "Garson", "hourly_wage": 100}, headers=h).json()
print(requests.patch(f"{API}/users/{member_uid}/assignment", json={"restaurant_id": ET, "staff_id": staff["id"]}, headers=h).status_code, file=sys.stderr)
def ticket(email):
    u = bapi(f"/users?email_address={urllib.parse.quote(email)}", method="GET")[0]
    return bapi("/sign_in_tokens", {"user_id": u["id"], "expires_in_seconds": 3600})["token"]
print(json.dumps({"prods": [prod["id"], norec["id"]], "inv": inv["id"], "staff": staff["id"], "staff_ticket": ticket("gokboss-member+clerk_test@example.com"), "admin_ticket": ticket("gokboss-admin+clerk_test@example.com")}))
