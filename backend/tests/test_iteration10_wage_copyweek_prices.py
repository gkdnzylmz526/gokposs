# Iteration 10: staff hourly_wage, POST /api/shifts/copy-week, GET /api/inventory/{id}/prices
import time
import uuid

import pytest
import requests
from dotenv import dotenv_values

BASE_URL = dotenv_values("/app/frontend/.env")["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
CREATED = {"expenses": [], "products": [], "inventory": [], "shifts": [], "staff": [], "suppliers": []}


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


def shifts_on(days):
    return [s for s in requests.get(f"{API}/dashboard").json()["shifts"] if s["date"] in days]


# --- Staff hourly wage
class TestStaffWage:
    def test_post_put_wage(self):
        s = create("staff", {"name": f"TEST_Wage_{tag()}", "hourly_wage": 125.5})
        assert s["hourly_wage"] == 125.5
        r = requests.put(f"{API}/staff/{s['id']}", json={**s, "hourly_wage": 150})
        assert r.status_code == 200 and r.json()["hourly_wage"] == 150
        got = next(x for x in requests.get(f"{API}/dashboard").json()["staff"] if x["id"] == s["id"])
        assert got["hourly_wage"] == 150

    def test_default_zero(self):
        s = create("staff", {"name": f"TEST_NoWage_{tag()}"})
        assert s["hourly_wage"] == 0


# --- Copy week (uses far-future weeks to avoid touching real data)
class TestCopyWeek:
    FROM, TO = "2031-03-03", "2031-03-10"  # Mondays
    SRC = [f"2031-03-{d:02d}" for d in range(3, 10)]
    DST = [f"2031-03-{d:02d}" for d in range(10, 17)]

    def test_copy_dup_deleted(self):
        a = create("staff", {"name": f"TEST_CwA_{tag()}", "hourly_wage": 100})
        create("shifts", {"staff_id": a["id"], "date": "2031-03-03", "start": "09:00", "end": "17:00", "task": "Kasa"})
        create("shifts", {"staff_id": a["id"], "date": "2031-03-09", "start": "22:00", "end": "02:00"})
        create("shifts", {"staff_id": a["id"], "date": "2031-03-02", "start": "09:00", "end": "17:00"})  # outside source week
        # orphan shift (staff not existing) -> must be skipped
        create("shifts", {"staff_id": f"ghost-{tag()}", "date": "2031-03-04", "start": "10:00", "end": "12:00"})
        # pre-existing duplicate in target
        create("shifts", {"staff_id": a["id"], "date": "2031-03-16", "start": "22:00", "end": "02:00"})
        r = requests.post(f"{API}/shifts/copy-week", json={"from_start": self.FROM, "to_start": self.TO})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["source_count"] == 3
        assert d["created"] == 1
        dst = [s for s in shifts_on(self.DST) if s["staff_id"] == a["id"]]
        CREATED["shifts"].extend(s["id"] for s in dst)
        keys = sorted((s["date"], s["start"], s["end"], s["task"]) for s in dst)
        assert keys == [("2031-03-10", "09:00", "17:00", "Kasa"), ("2031-03-16", "22:00", "02:00", "")]
        # second call -> 0
        r2 = requests.post(f"{API}/shifts/copy-week", json={"from_start": self.FROM, "to_start": self.TO})
        assert r2.json()["created"] == 0 and r2.json()["source_count"] == 3
        assert len([s for s in shifts_on(self.DST) if s["staff_id"] == a["id"]]) == 2

    def test_non_week_offset(self):
        # arbitrary offset of 14 days
        b = create("staff", {"name": f"TEST_CwB_{tag()}"})
        create("shifts", {"staff_id": b["id"], "date": "2032-05-05", "start": "08:00", "end": "12:00"})
        r = requests.post(f"{API}/shifts/copy-week", json={"from_start": "2032-05-03", "to_start": "2032-05-17"})
        assert r.status_code == 200 and r.json()["created"] == 1
        new = [s for s in shifts_on(["2032-05-19"]) if s["staff_id"] == b["id"]]
        CREATED["shifts"].extend(s["id"] for s in new)
        assert len(new) == 1

    def test_empty_source(self):
        r = requests.post(f"{API}/shifts/copy-week", json={"from_start": "2040-01-02", "to_start": "2040-01-09"})
        assert r.status_code == 200 and r.json() == {"created": 0, "source_count": 0}

    @pytest.mark.parametrize("body", [{"from_start": "bad", "to_start": "2031-03-10"}, {"from_start": "2031-02-30", "to_start": "2031-03-10"},
                                      {"to_start": "2031-03-10"}, {}])
    def test_invalid_422(self, body):
        assert requests.post(f"{API}/shifts/copy-week", json=body).status_code == 422


# --- Ingredient price history
class TestPrices:
    def test_unknown_404(self):
        assert requests.get(f"{API}/inventory/nope-{tag()}/prices").status_code == 404

    def test_history_comparison(self):
        t = tag()
        inv = create("inventory", {"name": f"TEST_Dom_{t}", "quantity": 0, "unit": "kg", "supplier": f"TEST_InvSup_{t}"})
        other = create("inventory", {"name": f"TEST_Other_{t}", "quantity": 0, "unit": "kg"})
        A, B = f"TEST_SupA_{t}", f"TEST_SupB_{t}"
        create("expenses", {"category": "TEST", "supplier": A, "purchases": [{"inventory_id": inv["id"], "quantity": 5, "unit_price": 30}]})
        time.sleep(0.05)
        create("expenses", {"category": "TEST", "supplier": A, "purchases": [{"inventory_id": inv["id"], "quantity": 3, "unit_price": 34}, {"inventory_id": other["id"], "quantity": 1, "unit_price": 99}]})
        time.sleep(0.05)
        create("expenses", {"category": "TEST", "supplier": B, "purchases": [{"inventory_id": inv["id"], "quantity": 2, "unit_price": 28}]})
        time.sleep(0.05)
        create("expenses", {"category": "TEST", "purchases": [{"inventory_id": inv["id"], "quantity": 1, "unit_price": 40}]})  # fallback supplier
        time.sleep(0.05)
        create("expenses", {"category": "TEST", "supplier": B, "amount": 10, "purchases": [{"inventory_id": inv["id"], "quantity": 4, "unit_price": 0}]})  # excluded
        r = requests.get(f"{API}/inventory/{inv['id']}/prices")
        assert r.status_code == 200
        d = r.json()
        assert d["item"]["id"] == inv["id"] and d["item"]["unit"] == "kg"
        assert d["item"]["unit_cost"] == 40
        h = d["history"]
        assert [x["unit_price"] for x in h] == [30, 34, 28, 40]
        assert [x["supplier"] for x in h] == [A, A, B, f"TEST_InvSup_{t}"]
        assert [x["date"] for x in h] == sorted(x["date"] for x in h)
        c = d["comparison"]
        assert [x["supplier"] for x in c] == [B, A, f"TEST_InvSup_{t}"]
        a = next(x for x in c if x["supplier"] == A)
        assert a["last_price"] == 34 and a["min_price"] == 30 and a["avg_price"] == 32 and a["purchases"] == 2 and a["quantity"] == 8
        b = next(x for x in c if x["supplier"] == B)
        assert b["purchases"] == 1 and b["quantity"] == 2 and b["last_price"] == 28

    def test_empty_history(self):
        inv = create("inventory", {"name": f"TEST_Empty_{tag()}", "quantity": 1})
        d = requests.get(f"{API}/inventory/{inv['id']}/prices").json()
        assert d["history"] == [] and d["comparison"] == []

    def test_no_supplier_label(self):
        inv = create("inventory", {"name": f"TEST_NoSup_{tag()}", "quantity": 0})
        create("expenses", {"category": "TEST", "purchases": [{"inventory_id": inv["id"], "quantity": 1, "unit_price": 12}]})
        d = requests.get(f"{API}/inventory/{inv['id']}/prices").json()
        assert d["history"][0]["supplier"] == "Tedarikçi belirtilmemiş"
