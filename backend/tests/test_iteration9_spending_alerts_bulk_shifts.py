# Iteration 9: supplier monthly spending, price-change alerts, bulk suggested price apply, shift calendar CRUD
import math
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import requests
from dotenv import dotenv_values

BASE_URL = dotenv_values("/app/frontend/.env")["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
TZ = ZoneInfo("Europe/Istanbul")
CREATED = {"inventory": [], "products": [], "expenses": [], "suppliers": [], "staff": [], "shifts": []}
ALERTS = []


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    for coll in ["expenses", "products", "inventory", "shifts", "staff", "suppliers"]:
        for i in CREATED[coll]:
            requests.delete(f"{API}/{coll}/{i}")


def create(coll, payload):
    r = requests.post(f"{API}/{coll}", json=payload)
    assert r.status_code == 200, r.text
    CREATED[coll].append(r.json()["id"])
    return r.json()


def tag():
    return uuid.uuid4().hex[:6]


def alerts_for(inv_id):
    r = requests.get(f"{API}/price-alerts")
    assert r.status_code == 200
    return [a for a in r.json() if a["inventory_id"] == inv_id]


# --- Supplier monthly spending
class TestSupplierSpending:
    def test_months_param_validation(self):
        for bad in [0, 25, -1]:
            assert requests.get(f"{API}/suppliers/spending", params={"months": bad}).status_code == 422
        for ok in [1, 3, 12, 24]:
            r = requests.get(f"{API}/suppliers/spending", params={"months": ok})
            assert r.status_code == 200
            assert len(r.json()["months"]) == ok

    def test_month_keys_istanbul(self):
        d = requests.get(f"{API}/suppliers/spending", params={"months": 3}).json()
        now = datetime.now(TZ)
        assert d["months"][-1] == now.strftime("%Y-%m")
        assert d["months"] == sorted(d["months"])
        assert len(set(d["months"])) == 3

    def test_default_6(self):
        assert len(requests.get(f"{API}/suppliers/spending").json()["months"]) == 6

    def test_explicit_derived_multi(self):
        t = tag()
        s1, s2 = f"TEST_SupA_{t}", f"TEST_SupB_{t}"
        create("suppliers", {"name": s1})
        create("suppliers", {"name": s2})
        i1 = create("inventory", {"name": f"TEST_Inv1_{t}", "quantity": 1, "unit": "kg", "unit_cost": 0, "supplier": s1})
        i2 = create("inventory", {"name": f"TEST_Inv2_{t}", "quantity": 1, "unit": "kg", "unit_cost": 0, "supplier": s2})
        # explicit supplier, no purchases
        create("expenses", {"category": "TEST", "amount": 1000, "supplier": s2})
        # derived from single inventory supplier
        create("expenses", {"category": "TEST", "purchases": [{"inventory_id": i1["id"], "quantity": 2, "unit_price": 50}]})
        # explicit overrides inventory supplier
        create("expenses", {"category": "TEST", "supplier": s2, "purchases": [{"inventory_id": i1["id"], "quantity": 1, "unit_price": 50}]})
        # multi-supplier
        create("expenses", {"category": "TEST", "purchases": [{"inventory_id": i1["id"], "quantity": 1, "unit_price": 50},
                                                              {"inventory_id": i2["id"], "quantity": 1, "unit_price": 30}]})
        d = requests.get(f"{API}/suppliers/spending", params={"months": 3}).json()
        rows = {r["supplier"]: r for r in d["rows"]}
        month = datetime.now(TZ).strftime("%Y-%m")
        assert rows[s1]["total"] == 100 and rows[s1]["count"] == 1
        assert rows[s1]["months"][month] == 100
        assert rows[s2]["total"] == 1050 and rows[s2]["count"] == 2
        assert set(rows[s2]["months"].keys()) == set(d["months"])
        assert "Birden fazla tedarikçi" in rows
        assert rows["Birden fazla tedarikçi"]["total"] >= 80
        totals = [r["total"] for r in d["rows"]]
        assert totals == sorted(totals, reverse=True)

    def test_no_supplier_excluded(self):
        e = create("expenses", {"category": "TEST", "amount": 77, "note": "TEST_no_supplier"})
        d = requests.get(f"{API}/suppliers/spending", params={"months": 1}).json()
        assert "" not in [r["supplier"] for r in d["rows"]]
        assert e["supplier"] == ""


# --- Price-change alerts
class TestPriceAlerts:
    def test_20pct_increase_creates_alert(self):
        t = tag()
        inv = create("inventory", {"name": f"TEST_Kiyma_{t}", "quantity": 5, "unit": "kg", "unit_cost": 600})
        prod = create("products", {"name": f"TEST_Burger_{t}", "price": 250, "recipe": [{"inventory_id": inv["id"], "amount": 0.15}]})
        assert prod["cost"] == 90
        create("expenses", {"category": "TEST", "purchases": [{"inventory_id": inv["id"], "quantity": 1, "unit_price": 720}]})
        al = alerts_for(inv["id"])
        assert len(al) == 1
        a = al[0]
        ALERTS.append(a["id"])
        assert a["old_price"] == 600 and a["new_price"] == 720 and a["change_pct"] == 20
        assert a["dismissed"] is False
        aff = next(x for x in a["affected"] if x["product_id"] == prod["id"])
        assert aff["old_cost"] == 90 and aff["new_cost"] == 108
        assert aff["old_margin"] == 64 and aff["new_margin"] == 56.8
        # dismiss
        r = requests.post(f"{API}/price-alerts/{a['id']}/dismiss")
        assert r.status_code == 200 and r.json()["ok"] is True
        assert alerts_for(inv["id"]) == []

    def test_small_increase_no_alert(self):
        t = tag()
        inv = create("inventory", {"name": f"TEST_Small_{t}", "quantity": 5, "unit": "kg", "unit_cost": 600})
        create("expenses", {"category": "TEST", "purchases": [{"inventory_id": inv["id"], "quantity": 1, "unit_price": 650}]})
        assert alerts_for(inv["id"]) == []

    def test_first_price_no_alert(self):
        t = tag()
        inv = create("inventory", {"name": f"TEST_First_{t}", "quantity": 0, "unit": "kg", "unit_cost": 0})
        create("expenses", {"category": "TEST", "purchases": [{"inventory_id": inv["id"], "quantity": 1, "unit_price": 500}]})
        assert alerts_for(inv["id"]) == []

    def test_exact_10pct_creates_alert(self):
        # spec: >= 10% higher -> alert. 600 -> 660 is exactly 10%
        t = tag()
        inv = create("inventory", {"name": f"TEST_Exact_{t}", "quantity": 5, "unit": "kg", "unit_cost": 600})
        create("expenses", {"category": "TEST", "purchases": [{"inventory_id": inv["id"], "quantity": 1, "unit_price": 660}]})
        al = alerts_for(inv["id"])
        for a in al:
            requests.post(f"{API}/price-alerts/{a['id']}/dismiss")
        assert len(al) == 1, "exact 10% increase (600->660) did not create alert (float precision)"

    def test_decrease_no_alert(self):
        t = tag()
        inv = create("inventory", {"name": f"TEST_Dec_{t}", "quantity": 5, "unit": "kg", "unit_cost": 600})
        create("expenses", {"category": "TEST", "purchases": [{"inventory_id": inv["id"], "quantity": 1, "unit_price": 400}]})
        assert alerts_for(inv["id"]) == []

    def test_dismiss_unknown_404(self):
        assert requests.post(f"{API}/price-alerts/nonexistent-{tag()}/dismiss").status_code == 404


# --- Bulk suggested price apply
class TestApplySuggested:
    def test_apply_only_given_ids(self):
        t = tag()
        p1 = create("products", {"name": f"TEST_P1_{t}", "price": 100, "cost": 70})  # suggested ceil(70/0.35)=200
        p2 = create("products", {"name": f"TEST_P2_{t}", "price": 100, "cost": 35})  # suggested 100 -> same
        p3 = create("products", {"name": f"TEST_P3_{t}", "price": 100, "cost": 50, "target_margin": 50})  # suggested 100 same
        p4 = create("products", {"name": f"TEST_P4_{t}", "price": 100, "cost": 60, "target_margin": 50})  # suggested 120 not given
        p5 = create("products", {"name": f"TEST_P5_{t}", "price": 100, "cost": 0})  # no suggestion
        r = requests.post(f"{API}/products/apply-suggested", json={"product_ids": [p1["id"], p2["id"], p3["id"], p5["id"]]})
        assert r.status_code == 200
        upd = r.json()["updated"]
        assert [u["id"] for u in upd] == [p1["id"]]
        assert upd[0]["old_price"] == 100 and upd[0]["new_price"] == math.ceil(70 / (1 - 0.65))
        prods = {p["id"]: p for p in requests.get(f"{API}/dashboard").json()["products"]}
        assert prods[p1["id"]]["price"] == 200
        assert prods[p4["id"]]["price"] == 100
        assert prods[p2["id"]]["price"] == 100
        assert prods[p5["id"]]["price"] == 100
        # idempotent
        r2 = requests.post(f"{API}/products/apply-suggested", json={"product_ids": [p1["id"]]})
        assert r2.json()["updated"] == []

    def test_empty_and_invalid(self):
        assert requests.post(f"{API}/products/apply-suggested", json={"product_ids": []}).json() == {"updated": []}
        assert requests.post(f"{API}/products/apply-suggested", json={}).json() == {"updated": []}
        assert requests.post(f"{API}/products/apply-suggested", json={"product_ids": "abc"}).status_code == 422


# --- Shifts CRUD + dashboard + cascade on staff delete
class TestShifts:
    def test_crud_dashboard_cascade(self):
        t = tag()
        staff = create("staff", {"name": f"TEST_Ali_{t}", "shift": "10:00 – 18:00", "task": "Kasa"})
        today = datetime.now(TZ).date()
        s1 = create("shifts", {"staff_id": staff["id"], "date": today.isoformat(), "start": "10:00", "end": "18:00", "task": "Kasa"})
        s2 = create("shifts", {"staff_id": staff["id"], "date": (today + timedelta(days=1)).isoformat(), "start": "22:00", "end": "02:00"})
        old = create("shifts", {"staff_id": staff["id"], "date": (today - timedelta(days=70)).isoformat()})
        assert old["start"] == "09:00" and old["end"] == "17:00"
        dash = {s["id"]: s for s in requests.get(f"{API}/dashboard").json()["shifts"]}
        assert s1["id"] in dash and s2["id"] in dash
        assert old["id"] in dash  # iteration 10: dashboard now returns all shifts (no 62-day window)
        assert dash[s1["id"]]["task"] == "Kasa"
        # update
        r = requests.put(f"{API}/shifts/{s1['id']}", json={**s1, "start": "11:00", "task": "Mutfak"})
        assert r.status_code == 200 and r.json()["start"] == "11:00"
        dash = {s["id"]: s for s in requests.get(f"{API}/dashboard").json()["shifts"]}
        assert dash[s1["id"]]["start"] == "11:00" and dash[s1["id"]]["task"] == "Mutfak"
        assert dash[s1["id"]]["created_at"] == s1["created_at"]
        # delete one
        assert requests.delete(f"{API}/shifts/{s2['id']}").status_code == 200
        assert requests.delete(f"{API}/shifts/{s2['id']}").status_code == 404
        # delete staff -> cascade
        assert requests.delete(f"{API}/staff/{staff['id']}").status_code == 200
        remaining = [s for s in requests.get(f"{API}/shifts").json() if s["staff_id"] == staff["id"]]
        assert remaining == []

    def test_put_unknown_404(self):
        r = requests.put(f"{API}/shifts/unknown-{tag()}", json={"staff_id": "x", "date": "2026-01-01"})
        assert r.status_code == 404

    def test_missing_required(self):
        assert requests.post(f"{API}/shifts", json={"date": "2026-01-01"}).status_code == 422
