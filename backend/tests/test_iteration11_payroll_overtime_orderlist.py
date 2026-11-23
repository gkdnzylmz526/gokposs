# Iteration 11: payroll + overtime (45h/week, 1.5x), payroll Excel export, smart order list (cheapest supplier), staff phone
import io
import os
import uuid

import pytest
import requests
from openpyxl import load_workbook

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
TAG = uuid.uuid4().hex[:6]

created = {"staff": [], "shifts": [], "inventory": [], "expenses": [], "suppliers": []}


def post(col, payload):
    r = requests.post(f"{API}/{col}", json=payload, timeout=30)
    assert r.status_code == 200, r.text
    doc = r.json()
    created[col].append(doc["id"])
    return doc


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    for col in ("expenses", "shifts", "staff", "inventory", "suppliers"):
        for i in created[col]:
            requests.delete(f"{API}/{col}/{i}", timeout=30)


def row_for(data, staff_id):
    return next(r for r in data["rows"] if r["staff_id"] == staff_id)


# ---------- Payroll / overtime ----------
class TestPayroll:
    def test_staff_phone_and_wage_persist(self):
        s = post("staff", {"name": f"TEST_Ali_{TAG}", "hourly_wage": 100, "phone": "0532 000 00 01"})
        assert s["phone"] == "0532 000 00 01" and s["hourly_wage"] == 100
        got = requests.get(f"{API}/dashboard").json()["staff"]
        me = next(x for x in got if x["id"] == s["id"])
        assert me["phone"] == "0532 000 00 01"
        # update phone
        r = requests.put(f"{API}/staff/{s['id']}", json={**s, "phone": "05320000002"})
        assert r.status_code == 200 and r.json()["phone"] == "05320000002"

    def test_six_nine_hour_shifts_overtime(self):
        s = post("staff", {"name": f"TEST_OT_{TAG}", "hourly_wage": 100})
        # 2031-06-02 is Monday
        for d in range(2, 8):
            post("shifts", {"staff_id": s["id"], "date": f"2031-06-0{d}", "start": "09:00", "end": "18:00"})
        data = requests.get(f"{API}/payroll", params={"month": "2031-06"}).json()
        r = row_for(data, s["id"])
        assert r["shift_count"] == 6
        assert r["regular_hours"] == 45 and r["overtime_hours"] == 9
        assert r["regular_pay"] == 4500 and r["overtime_pay"] == 1350 and r["total_pay"] == 5850
        # chronological allocation: last shift (Sat) is overtime
        assert [x["overtime"] for x in r["shifts"]] == [0, 0, 0, 0, 0, 9]
        assert data["weekly_limit"] == 45 and data["overtime_rate"] == 1.5
        # totals = sum of rows
        for k in ("regular_hours", "overtime_hours", "regular_pay", "overtime_pay", "total_pay"):
            assert abs(data["totals"][k] - sum(x[k] for x in data["rows"])) < 0.01

    def test_month_boundary_week(self):
        # 2031-03-01 is Saturday -> week Mon 2031-02-24 .. Sun 2031-03-02
        s = post("staff", {"name": f"TEST_Bnd_{TAG}", "hourly_wage": 200})
        for d in ("2031-02-24", "2031-02-25", "2031-02-26", "2031-02-27", "2031-02-28"):
            post("shifts", {"staff_id": s["id"], "date": d, "start": "08:00", "end": "18:00"})  # 10h x5 = 50
        for d in ("2031-03-01", "2031-03-02"):
            post("shifts", {"staff_id": s["id"], "date": d, "start": "09:00", "end": "18:00"})  # 9h x2
        post("shifts", {"staff_id": s["id"], "date": "2031-03-03", "start": "09:00", "end": "17:00"})  # new week 8h regular
        feb = row_for(requests.get(f"{API}/payroll", params={"month": "2031-02"}).json(), s["id"])
        assert feb["shift_count"] == 5 and feb["regular_hours"] == 45 and feb["overtime_hours"] == 5
        assert feb["total_pay"] == 45 * 200 + 5 * 300
        mar = row_for(requests.get(f"{API}/payroll", params={"month": "2031-03"}).json(), s["id"])
        assert mar["shift_count"] == 3
        assert mar["regular_hours"] == 8 and mar["overtime_hours"] == 18
        assert mar["regular_pay"] == 1600 and mar["overtime_pay"] == 18 * 300

    def test_overnight_shift_hours(self):
        s = post("staff", {"name": f"TEST_Night_{TAG}", "hourly_wage": 50})
        post("shifts", {"staff_id": s["id"], "date": "2031-08-04", "start": "22:00", "end": "06:00"})
        r = row_for(requests.get(f"{API}/payroll", params={"month": "2031-08"}).json(), s["id"])
        assert r["regular_hours"] == 8 and r["total_pay"] == 400

    @pytest.mark.parametrize("bad", ["2031-13", "2031-1", "abcd-ef", "2031-00"])
    def test_invalid_month_422(self, bad):
        assert requests.get(f"{API}/payroll", params={"month": bad}).status_code == 422
        assert requests.get(f"{API}/payroll/export", params={"month": bad}).status_code == 422

    def test_default_month(self):
        r = requests.get(f"{API}/payroll")
        assert r.status_code == 200 and len(r.json()["month"]) == 7

    def test_export_xlsx(self):
        r = requests.get(f"{API}/payroll/export", params={"month": "2031-06"})
        assert r.status_code == 200
        assert "spreadsheetml" in r.headers["content-type"]
        assert "gokboss-pos-maas-2031-06.xlsx" in r.headers.get("content-disposition", "")
        wb = load_workbook(io.BytesIO(r.content))
        assert wb.sheetnames[:2] == ["Maaş Özeti", "Vardiya Detayı"]  # iter12 adds "Avanslar"
        ws = wb["Maaş Özeti"]
        rows = [[c.value for c in row] for row in ws.iter_rows()]
        mine = next(x for x in rows if x[0] == f"TEST_OT_{TAG}")
        assert mine[2:9] == [100, 6, 45, 9, 4500, 1350, 5850]
        assert any(x[0] == "TOPLAM" for x in rows)
        det = [[c.value for c in row] for row in wb["Vardiya Detayı"].iter_rows()]
        mydet = [x for x in det if x[0] == f"TEST_OT_{TAG}"]
        assert len(mydet) == 6 and mydet[0][1] == "02.06.2031" and mydet[-1][5] == 9


# ---------- Smart order list ----------
class TestOrderList:
    def test_cheapest_supplier_grouping(self):
        a, b = f"TEST_SupA_{TAG}", f"TEST_SupB_{TAG}"
        post("suppliers", {"name": a, "phone": "05550000001"})
        post("suppliers", {"name": b, "phone": "05550000002"})
        inv = post("inventory", {"name": f"TEST_Dom_{TAG}", "quantity": 2, "unit": "kg", "minimum": 10, "unit_cost": 34, "supplier": a})
        post("expenses", {"category": "Malzeme", "supplier": a, "purchases": [{"inventory_id": inv["id"], "quantity": 1, "unit_price": 34}]})
        post("expenses", {"category": "Malzeme", "supplier": b, "purchases": [{"inventory_id": inv["id"], "quantity": 1, "unit_price": 28}]})
        groups = requests.get(f"{API}/order-list").json()
        g = next(x for x in groups if any(i["inventory_id"] == inv["id"] for i in x["items"]))
        assert g["supplier"] == b and g["phone"] == "05550000002"
        item = next(i for i in g["items"] if i["inventory_id"] == inv["id"])
        assert item["suggested"] == 16  # 20 - (2+1+1)
        assert item["unit_price"] == 28 and item["assigned_supplier"] == a and item["cheapest"] is True
        assert item["saving"] == (34 - 28) * 16 and item["estimated_cost"] == 28 * 16
        assert not any(i["inventory_id"] == inv["id"] for x in groups if x["supplier"] == a for i in x["items"])

    def test_single_supplier_history_stays_assigned(self):
        a = f"TEST_SupC_{TAG}"
        post("suppliers", {"name": a, "phone": "05550000003"})
        inv = post("inventory", {"name": f"TEST_Sog_{TAG}", "quantity": 1, "unit": "kg", "minimum": 5, "unit_cost": 10, "supplier": a})
        post("expenses", {"category": "Malzeme", "supplier": a, "purchases": [{"inventory_id": inv["id"], "quantity": 1, "unit_price": 12}]})
        g = next(x for x in requests.get(f"{API}/order-list").json() if any(i["inventory_id"] == inv["id"] for i in x["items"]))
        item = next(i for i in g["items"] if i["inventory_id"] == inv["id"])
        assert g["supplier"] == a and g["phone"] == "05550000003"
        assert item["cheapest"] is False and item["saving"] == 0 and item["unit_price"] == 12

    def test_no_history_fallback(self):
        a = f"TEST_SupD_{TAG}"
        inv = post("inventory", {"name": f"TEST_Biber_{TAG}", "quantity": 0, "unit": "kg", "minimum": 3, "target": 10, "unit_cost": 15, "supplier": a})
        g = next(x for x in requests.get(f"{API}/order-list").json() if any(i["inventory_id"] == inv["id"] for i in x["items"]))
        item = next(i for i in g["items"] if i["inventory_id"] == inv["id"])
        assert g["supplier"] == a and g["phone"] == ""  # supplier not in suppliers collection
        assert item["cheapest"] is False and item["unit_price"] == 15 and item["suggested"] == 10 and item["estimated_cost"] == 150

    def test_price_insights_regression(self):
        inv_id = created["inventory"][0]
        d = requests.get(f"{API}/inventory/{inv_id}/prices").json()
        assert [c["last_price"] for c in d["comparison"]] == [28, 34]
        assert requests.get(f"{API}/inventory/nope/prices").status_code == 404


# ---------- Regression: shifts CRUD + copy-week ----------
class TestShiftRegression:
    def test_shift_crud_and_copy_week(self):
        s = post("staff", {"name": f"TEST_Copy_{TAG}", "hourly_wage": 10})
        sh = post("shifts", {"staff_id": s["id"], "date": "2032-05-03", "start": "10:00", "end": "14:00"})
        r = requests.put(f"{API}/shifts/{sh['id']}", json={**sh, "end": "15:00"})
        assert r.status_code == 200 and r.json()["end"] == "15:00"
        assert requests.post(f"{API}/shifts", json={"staff_id": s["id"], "date": "bad", "start": "10:00", "end": "14:00"}).status_code == 422
        c = requests.post(f"{API}/shifts/copy-week", json={"from_start": "2032-05-03", "to_start": "2032-05-10"}).json()
        assert c["created"] == 1
        copied = [x for x in requests.get(f"{API}/dashboard").json()["shifts"] if x["staff_id"] == s["id"] and x["date"] == "2032-05-10"]
        assert len(copied) == 1 and copied[0]["end"] == "15:00"
        created["shifts"].append(copied[0]["id"])
        assert requests.post(f"{API}/shifts/copy-week", json={"from_start": "2032-05-03", "to_start": "2032-05-10"}).json()["created"] == 0
