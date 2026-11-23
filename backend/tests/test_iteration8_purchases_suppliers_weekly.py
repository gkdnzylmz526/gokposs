# Iteration 8: weekly summary cron auth, purchase expenses (stock/unit_cost/recipe cost), suppliers CRUD + order-list phone
import os
import time
import uuid
import pytest
import requests
from dotenv import dotenv_values

BASE_URL = dotenv_values("/app/frontend/.env")["REACT_APP_BACKEND_URL"].rstrip("/")
SECRET = dotenv_values("/app/backend/.env").get("WEBHOOK_CRON_SECRET")
API = f"{BASE_URL}/api"
CREATED = {"inventory": [], "products": [], "expenses": [], "suppliers": []}


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    for coll, ids in CREATED.items():
        for i in ids:
            requests.delete(f"{API}/{coll}/{i}")


def create(coll, payload):
    r = requests.post(f"{API}/{coll}", json=payload)
    assert r.status_code == 200, r.text
    CREATED[coll].append(r.json()["id"])
    return r.json()


def inv(item_id):
    return next(i for i in requests.get(f"{API}/dashboard").json()["inventory"] if i["id"] == item_id)


# --- Weekly summary cron auth
class TestWeeklyCron:
    def test_no_auth(self):
        assert requests.post(f"{API}/cron/weekly-summary").status_code == 401

    def test_wrong_bearer(self):
        r = requests.post(f"{API}/cron/weekly-summary", headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 401

    @pytest.mark.skipif(os.environ.get("RUN_REAL_EMAIL_CRON") != "1", reason="sends a real email; opt-in only")
    def test_accepted_then_duplicate(self):
        run_id = f"TEST_weekly_{uuid.uuid4()}"
        h = {"Authorization": f"Bearer {SECRET}", "X-Webhook-Id": run_id}
        r = requests.post(f"{API}/cron/weekly-summary", headers=h)
        assert r.status_code == 200 and r.json()["status"] == "accepted"
        r2 = requests.post(f"{API}/cron/weekly-summary", headers=h)
        assert r2.status_code == 200 and r2.json()["status"] == "duplicate"
        rec = None
        for _ in range(15):
            time.sleep(2)
            rec = next((x for x in requests.get(f"{API}/email/status").json()["history"] if x.get("key") == run_id), None)
            if rec:
                break
        print("delivery record:", rec)
        assert rec and rec["kind"] == "weekly" and rec["trigger"] == "cron" and rec["status"] == "sent"


# --- Purchase expenses
class TestPurchases:
    def test_purchase_lifecycle(self):
        item = create("inventory", {"name": "TEST_Kiyma", "quantity": 1, "unit": "kg", "minimum": 5, "unit_cost": 600})
        prod = create("products", {"name": "TEST_Kofte", "price": 250, "recipe": [{"inventory_id": item["id"], "amount": 0.15}]})
        assert prod["cost"] == 90.0 and prod["cost_from_recipe"]

        exp = create("expenses", {"category": "Et", "purchases": [{"inventory_id": item["id"], "quantity": 10, "unit_price": 650}]})
        assert exp["amount"] == 6500
        i = inv(item["id"])
        assert i["quantity"] == 11 and i["unit_cost"] == 650
        moves = requests.get(f"{API}/stock-movements", params={"inventory_id": item["id"]}).json()
        assert any(m["reason"] == "Alış · Et" and m["delta"] == 10 and m["quantity_after"] == 11 for m in moves)
        p = next(x for x in requests.get(f"{API}/dashboard").json()["products"] if x["id"] == prod["id"])
        assert p["cost"] == 97.5

        # Edit: qty 10 -> 5, amount left at 0 so it recomputes
        r = requests.put(f"{API}/expenses/{exp['id']}", json={**exp, "amount": 0, "purchases": [{"inventory_id": item["id"], "quantity": 5, "unit_price": 650}]})
        assert r.status_code == 200 and r.json()["amount"] == 3250
        assert inv(item["id"])["quantity"] == 6

        assert requests.delete(f"{API}/expenses/{exp['id']}").status_code == 200
        CREATED["expenses"].remove(exp["id"])
        assert inv(item["id"])["quantity"] == 1
        reasons = [m["reason"] for m in requests.get(f"{API}/stock-movements", params={"inventory_id": item["id"]}).json()]
        assert "Alış silindi (stoktan çıkarıldı)" in reasons

    def test_edit_with_stale_amount_keeps_old_amount(self):
        """Frontend edit sends existing amount; check whether amount follows new purchase total."""
        item = create("inventory", {"name": "TEST_Sogan", "quantity": 0, "unit": "kg", "unit_cost": 10})
        exp = create("expenses", {"category": "Sebze", "purchases": [{"inventory_id": item["id"], "quantity": 10, "unit_price": 20}]})
        r = requests.put(f"{API}/expenses/{exp['id']}", json={**exp, "purchases": [{"inventory_id": item["id"], "quantity": 5, "unit_price": 20}]})
        print("amount after edit with stale amount:", r.json()["amount"])
        assert inv(item["id"])["quantity"] == 5
        assert r.json()["amount"] == 100, "amount stays at old 200 when the client re-sends it"

    def test_manual_amount_kept(self):
        item = create("inventory", {"name": "TEST_Yag", "quantity": 0, "unit": "lt"})
        exp = create("expenses", {"category": "Yağ", "amount": 999, "purchases": [{"inventory_id": item["id"], "quantity": 2, "unit_price": 100}]})
        assert exp["amount"] == 999
        assert inv(item["id"])["quantity"] == 2 and inv(item["id"])["unit_cost"] == 100

    def test_plain_expense_no_purchases(self):
        exp = create("expenses", {"category": "Kira", "amount": 1234})
        assert exp["amount"] == 1234 and exp["purchases"] == []


# --- Suppliers
class TestSuppliers:
    def test_supplier_crud_and_order_list_phone(self):
        s = create("suppliers", {"name": "TEST_Manav Veli", "phone": "0532 111 22 33", "note": "sebze"})
        assert s["phone"] == "0532 111 22 33"
        dash = requests.get(f"{API}/dashboard").json()
        assert any(x["id"] == s["id"] for x in dash["suppliers"])
        r = requests.put(f"{API}/suppliers/{s['id']}", json={**s, "note": "meyve"})
        assert r.status_code == 200 and r.json()["note"] == "meyve"
        create("inventory", {"name": "TEST_Domates", "quantity": 1, "unit": "kg", "minimum": 5, "unit_cost": 30, "supplier": "TEST_Manav Veli"})
        group = next(g for g in requests.get(f"{API}/order-list").json() if g["supplier"] == "TEST_Manav Veli")
        assert group["phone"] == "0532 111 22 33"
        assert group["items"][0]["suggested"] == 9
        assert requests.delete(f"{API}/suppliers/{s['id']}").status_code == 200
        CREATED["suppliers"].remove(s["id"])
        assert requests.delete(f"{API}/suppliers/{s['id']}").status_code == 404
        group = next(g for g in requests.get(f"{API}/order-list").json() if g["supplier"] == "TEST_Manav Veli")
        assert group["phone"] == ""

    def test_supplier_requires_name(self):
        assert requests.post(f"{API}/suppliers", json={"phone": "1"}).status_code == 422
