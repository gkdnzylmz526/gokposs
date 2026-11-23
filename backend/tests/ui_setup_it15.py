# UI setup for iteration 15: creates TEST_ product+inventory (admin) and prints ids + sign-in tickets. Usage: python3 tests/ui_setup_it15.py [cleanup <prod> <inv>]
import sys, json, urllib.parse, requests
from clerk_helper import user_and_token, bapi
API = open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split()[0].rstrip("/") + "/api"
_, tok = user_and_token("gokboss-admin+clerk_test@example.com")
h = {"Authorization": f"Bearer {tok}"}
if len(sys.argv) > 1 and sys.argv[1] == "cleanup":
    pid, iid = sys.argv[2], sys.argv[3]
    for s in requests.get(f"{API}/sales", headers=h).json():
        if s.get("product_id") == pid:
            print("del sale", requests.delete(f"{API}/sales/{s['id']}", headers=h).status_code)
    print(requests.delete(f"{API}/products/{pid}", headers=h).status_code, requests.delete(f"{API}/inventory/{iid}", headers=h).status_code)
    sys.exit()
inv = requests.post(f"{API}/inventory", json={"name": "TEST_UI_Et", "quantity": 20, "unit": "kg", "minimum": 2, "unit_cost": 10}, headers=h).json()
prod = requests.post(f"{API}/products", json={"name": "TEST_UI_Kebap", "category": "TEST", "price": 150, "recipe": [{"inventory_id": inv["id"], "amount": 0.25}]}, headers=h).json()
def ticket(email):
    u = bapi(f"/users?email_address={urllib.parse.quote(email)}", method="GET")[0]
    return bapi("/sign_in_tokens", {"user_id": u["id"], "expires_in_seconds": 3600})["token"]
print(json.dumps({"prod": prod["id"], "inv": inv["id"], "staff_ticket": ticket("gokboss-member+clerk_test@example.com"), "admin_ticket": ticket("gokboss-admin+clerk_test@example.com")}))
