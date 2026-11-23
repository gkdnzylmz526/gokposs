# Iteration 19 UI helper: print member user state / inventory & tables per restaurant (read-only).
import sys, json, requests
from clerk_helper import user_and_token
API = open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split()[0].rstrip("/") + "/api"
_, tok = user_and_token("gokboss-admin+clerk_test@example.com")
h = {"Authorization": f"Bearer {tok}"}
for u in requests.get(f"{API}/users", headers=h).json()["users"]:
    if "clerk_test" in u.get("email", ""):
        print({k: u.get(k) for k in ("user_id", "email", "role", "restaurant_id", "staff_id")})
for rid in ("florya-tasfirin", "etiler-marmaris", "durumtir"):
    hh = {**h, "X-Restaurant": rid}
    inv = [(i["name"], i["quantity"], i["id"]) for i in requests.get(f"{API}/inventory", headers=hh).json() if "TEST" in i["name"]]
    tr = requests.get(f"{API}/stock-transfers", headers=hh).json()
    tb = [t["name"] for t in requests.get(f"{API}/tables", headers=hh).json()]
    kt = requests.get(f"{API}/kitchen", headers=hh).json()
    print(rid, "TESTinv", inv, "transfers", len(tr), "tables", tb, "kitchen", len(kt))
