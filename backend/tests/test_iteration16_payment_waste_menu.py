# Iteration 16: payment types, reports/reconciliation payment breakdown, waste CRUD + stock math, staff my_today, public QR menu, cash-reminder cron auth.
import uuid

import pytest
import requests

from conftest import get_token, MEMBER_EMAIL, ADMIN_EMAIL

BASE_URL = open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split()[0].rstrip("/")
API = f"{BASE_URL}/api"
STAFF_EMAIL = MEMBER_EMAIL
SFX = uuid.uuid4().hex[:5]
created = {"products": [], "inventory": [], "sales": [], "waste": []}


def H(email):
    return {"Authorization": f"Bearer {get_token(email)[1]}"}


def inv_qty(iid):
    return next(x for x in requests.get(f"{API}/inventory", headers=H(ADMIN_EMAIL)).json() if x["id"] == iid)["quantity"]


@pytest.fixture(scope="module", autouse=True)
def data():
    a = H(ADMIN_EMAIL)
    inv = requests.post(f"{API}/inventory", json={"name": f"TEST_İçli_{SFX}", "quantity": 10, "unit": "kg", "minimum": 1, "unit_cost": 12.5}, headers=a).json()
    created["inventory"].append(inv["id"])
    prod = requests.post(f"{API}/products", json={"name": f"TEST_it16_prod_{SFX}", "category": "TEST16", "price": 100, "cost": 30,
                                                 "recipe": [{"inventory_id": inv["id"], "amount": 0.1}]}, headers=a).json()
    created["products"].append(prod["id"])
    inactive = requests.post(f"{API}/products", json={"name": f"TEST_it16_inactive_{SFX}", "category": "TEST16", "price": 77, "active": False}, headers=a).json()
    created["products"].append(inactive["id"])
    yield {"inv": inv, "prod": prod, "inactive": inactive}
    for k in ("waste", "sales", "products", "inventory"):
        for i in created[k]:
            requests.delete(f"{API}/{k}/{i}", headers=a)


# --- Payment type
class TestPayment:
    def test_invalid_payment_422(self, data):
        r = requests.post(f"{API}/sales", json={"product_id": data["prod"]["id"], "product_name": data["prod"]["name"], "quantity": 1, "unit_price": 100, "amount": 100, "payment": "Bitcoin"}, headers=H(ADMIN_EMAIL))
        assert r.status_code == 422

    def test_default_nakit_and_breakdown(self, data):
        a = H(ADMIN_EMAIL)
        before_rep = requests.get(f"{API}/reports", params={"period": "daily"}, headers=a).json()
        before_rec = requests.get(f"{API}/cash/reconciliation", headers=a).json()
        ids = []
        for pay, amt in ((None, 100), ("Kart", 200), ("Yemek kartı", 300)):
            body = {"product_id": data["prod"]["id"], "product_name": data["prod"]["name"], "quantity": amt / 100, "unit_price": 100, "amount": amt}
            if pay:
                body["payment"] = pay
            r = requests.post(f"{API}/sales", json=body, headers=a)
            assert r.status_code == 200, r.text
            ids.append(r.json()["id"]); created["sales"].append(r.json()["id"])
            assert r.json()["payment"] == (pay or "Nakit")
            assert r.json()["created_by"] == ADMIN_EMAIL
        stored = {s["id"]: s for s in requests.get(f"{API}/sales", headers=a).json()}
        assert stored[ids[1]]["payment"] == "Kart"
        rep = requests.get(f"{API}/reports", params={"period": "daily"}, headers=a).json()
        print("reports payments", before_rep.get("payments"), "->", rep["payments"])
        assert set(rep["payments"]) == {"Nakit", "Kart", "Yemek kartı"}
        for k, d in (("Nakit", 100), ("Kart", 200), ("Yemek kartı", 300)):
            assert round(rep["payments"][k] - before_rep["payments"][k], 2) == d
        rec = requests.get(f"{API}/cash/reconciliation", headers=a).json()
        assert round(rec["cash_sales"] - before_rec["cash_sales"], 2) == 100
        assert round(rec["payments"]["Kart"] - before_rec["payments"]["Kart"], 2) == 200
        assert round(rec["sales"] - before_rec["sales"], 2) == 600
        assert round(rec["expected_closing"], 2) == round(rec["opening"] + rec["cash_sales"] - rec["expenses"], 2)

    def test_update_keeps_created_by_and_payment_change(self, data):
        a = H(ADMIN_EMAIL)
        s = requests.post(f"{API}/sales", json={"product_id": data["prod"]["id"], "product_name": data["prod"]["name"], "quantity": 1, "unit_price": 100, "amount": 100}, headers=a).json()
        created["sales"].append(s["id"])
        r = requests.put(f"{API}/sales/{s['id']}", json={**s, "payment": "Kart", "created_by": "hacker@x.com"}, headers=a)
        assert r.status_code == 200 and r.json()["payment"] == "Kart" and r.json()["created_by"] == ADMIN_EMAIL
        assert requests.put(f"{API}/sales/{s['id']}", json={**s, "payment": "kart"}, headers=a).status_code == 422


# --- Waste CRUD
class TestWaste:
    def test_validation(self, data):
        a = H(ADMIN_EMAIL)
        assert requests.post(f"{API}/waste", json={"inventory_name": f"TEST_nope_{SFX}", "quantity": 1}, headers=a).status_code == 422
        assert requests.post(f"{API}/waste", json={"inventory_name": data["inv"]["name"], "quantity": 0}, headers=a).status_code == 422
        assert requests.post(f"{API}/waste", json={"inventory_name": data["inv"]["name"], "quantity": -2}, headers=a).status_code == 422
        assert requests.post(f"{API}/waste", json={"inventory_name": "", "quantity": 1}, headers=a).status_code == 422

    def test_crud_stock_math(self, data):
        a = H(ADMIN_EMAIL)
        iid = data["inv"]["id"]
        q0 = inv_qty(iid)
        rep0 = requests.get(f"{API}/reports", params={"period": "daily"}, headers=a).json()
        # Turkish/case-insensitive match: "TEST_İçli" -> "test_içli"
        r = requests.post(f"{API}/waste", json={"inventory_name": f"  test_içli_{SFX} ", "quantity": 2, "reason": "Bozuldu", "note": "TEST_note", "cost": 9999, "inventory_id": ""}, headers=a)
        assert r.status_code == 200, r.text
        w = r.json(); created["waste"].append(w["id"])
        assert w["inventory_id"] == iid and w["inventory_name"] == data["inv"]["name"] and w["unit"] == "kg" and w["cost"] == 25.0
        assert round(inv_qty(iid), 3) == round(q0 - 2, 3)
        mv = requests.get(f"{API}/stock-movements", params={"inventory_id": iid}, headers=a).json()
        assert mv[0]["reason"] == "Fire · Bozuldu" and mv[0]["delta"] == -2
        assert any(x["id"] == w["id"] for x in requests.get(f"{API}/waste", headers=a).json())
        rep = requests.get(f"{API}/reports", params={"period": "daily"}, headers=a).json()
        assert rep["waste_count"] - rep0["waste_count"] == 1 and round(rep["waste_cost"] - rep0["waste_cost"], 2) == 25.0
        # edit: 2 -> 3
        r = requests.put(f"{API}/waste/{w['id']}", json={**w, "quantity": 3, "reason": "Döküldü"}, headers=a)
        assert r.status_code == 200, r.text
        assert r.json()["cost"] == 37.5
        assert round(inv_qty(iid), 3) == round(q0 - 3, 3)
        # delete restores
        assert requests.delete(f"{API}/waste/{w['id']}", headers=a).status_code == 200
        assert round(inv_qty(iid), 3) == round(q0, 3)
        assert requests.delete(f"{API}/waste/{w['id']}", headers=a).status_code == 404
        mv = requests.get(f"{API}/stock-movements", params={"inventory_id": iid}, headers=a).json()
        assert mv[0]["reason"] == "Fire silindi (stok iade)"

    def test_update_invalid_name_no_stock_drift(self, data):
        a = H(ADMIN_EMAIL)
        iid = data["inv"]["id"]
        w = requests.post(f"{API}/waste", json={"inventory_name": data["inv"]["name"], "quantity": 1}, headers=a).json()
        created["waste"].append(w["id"])
        q1 = inv_qty(iid)
        r = requests.put(f"{API}/waste/{w['id']}", json={**w, "inventory_name": f"TEST_nope_{SFX}"}, headers=a)
        print("update invalid name:", r.status_code, "qty before", q1, "after", inv_qty(iid))
        assert r.status_code == 422
        assert round(inv_qty(iid), 3) == round(q1, 3), "stock drifted after failed waste update (old reversal not rolled back)"

    def test_staff_forbidden(self, data):
        assert requests.get(f"{API}/waste", headers=H(STAFF_EMAIL)).status_code == 403
        assert requests.post(f"{API}/waste", json={"inventory_name": data["inv"]["name"], "quantity": 1}, headers=H(STAFF_EMAIL)).status_code == 403


# --- Staff today summary
class TestStaffToday:
    def test_my_today(self, data):
        sh = H(STAFF_EMAIL)
        assert requests.get(f"{API}/me", headers=sh).json()["role"] == "staff"
        before = {r["product_name"]: r["quantity"] for r in requests.get(f"{API}/staff-view", headers=sh).json()["my_today"]}
        for q in (2, 1):
            s = requests.post(f"{API}/sales", json={"product_id": data["prod"]["id"], "quantity": q, "payment": "Kart"}, headers=sh)
            assert s.status_code == 200 and s.json()["payment"] == "Kart" and s.json()["created_by"] == STAFF_EMAIL
            created["sales"].append(s.json()["id"])
        # admin sale of same product must not count for the staff member
        s = requests.post(f"{API}/sales", json={"product_id": data["prod"]["id"], "product_name": data["prod"]["name"], "quantity": 5, "unit_price": 100, "amount": 500}, headers=H(ADMIN_EMAIL)).json()
        created["sales"].append(s["id"])
        d = requests.get(f"{API}/staff-view", headers=sh).json()
        mine = {r["product_name"]: r["quantity"] for r in d["my_today"]}
        assert mine[data["prod"]["name"]] - before.get(data["prod"]["name"], 0) == 3
        assert all(set(r) == {"product_name", "quantity"} for r in d["my_today"])

    def test_staff_cannot_spoof_created_by(self, data):
        s = requests.post(f"{API}/sales", json={"product_id": data["prod"]["id"], "quantity": 1, "created_by": "someone@else.com"}, headers=H(STAFF_EMAIL)).json()
        created["sales"].append(s["id"])
        assert s["created_by"] == STAFF_EMAIL


# --- Public menu
class TestPublicMenu:
    def test_no_auth(self, data):
        r = requests.get(f"{API}/public/menu", headers={"X-No-Auth": "1"})
        assert r.status_code == 200
        m = r.json()
        assert m["name"] == "GÖKBOSS"
        cat = next(c for c in m["categories"] if c["category"] == "TEST16")
        names = [i["name"] for i in cat["items"]]
        assert data["prod"]["name"] in names and data["inactive"]["name"] not in names
        for c in m["categories"]:
            for i in c["items"]:
                assert set(i) == {"name", "price"}
        assert [c["category"] for c in m["categories"]] == sorted(c["category"] for c in m["categories"])


# --- Cron
class TestCron:
    def test_cash_reminder_unauthorized(self):
        assert requests.post(f"{API}/cron/cash-reminder", headers={"X-No-Auth": "1"}).status_code == 401
        assert requests.post(f"{API}/cron/cash-reminder", headers={"Authorization": "Bearer wrong-secret"}).status_code == 401
