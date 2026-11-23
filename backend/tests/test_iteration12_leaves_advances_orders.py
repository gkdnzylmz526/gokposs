# Iteration 12: leaves CRUD, salary advances in payroll + export, order history CRUD, staff cascade delete
import io
import os
import uuid

import pytest
import requests
from openpyxl import load_workbook

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
TAG = uuid.uuid4().hex[:6]

created = {"staff": [], "shifts": [], "leaves": [], "advances": [], "orders": []}


def post(col, payload):
    r = requests.post(f"{API}/{col}", json=payload, timeout=30)
    assert r.status_code == 200, r.text
    doc = r.json()
    created[col].append(doc["id"])
    return doc


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    for col in ("orders", "advances", "leaves", "shifts", "staff"):
        for i in created[col]:
            requests.delete(f"{API}/{col}/{i}", timeout=30)


def row_for(data, sid):
    return next(r for r in data["rows"] if r["staff_id"] == sid)


# ---------- Leaves ----------
class TestLeaves:
    def test_staff_default_annual_leave(self):
        s = post("staff", {"name": f"TEST_Lv_{TAG}"})
        assert s["annual_leave_days"] == 14
        s2 = post("staff", {"name": f"TEST_Lv2_{TAG}", "annual_leave_days": 20})
        assert s2["annual_leave_days"] == 20

    def test_leave_crud(self):
        sid = created["staff"][0]
        lv = post("leaves", {"staff_id": sid, "date": "2033-04-05", "type": "Raporlu", "note": "grip"})
        assert lv["type"] == "Raporlu" and lv["note"] == "grip"
        dash = requests.get(f"{API}/dashboard").json()
        assert "leaves" in dash and "advances" in dash
        assert any(x["id"] == lv["id"] for x in dash["leaves"])
        r = requests.put(f"{API}/leaves/{lv['id']}", json={**lv, "type": "Yıllık izin"})
        assert r.status_code == 200 and r.json()["type"] == "Yıllık izin"
        got = next(x for x in requests.get(f"{API}/dashboard").json()["leaves"] if x["id"] == lv["id"])
        assert got["type"] == "Yıllık izin"
        assert requests.delete(f"{API}/leaves/{lv['id']}").status_code == 200
        assert requests.delete(f"{API}/leaves/{lv['id']}").status_code == 404
        assert not any(x["id"] == lv["id"] for x in requests.get(f"{API}/dashboard").json()["leaves"])

    def test_leave_default_type(self):
        lv = post("leaves", {"staff_id": created["staff"][0], "date": "2033-04-06"})
        assert lv["type"] == "Yıllık izin"

    @pytest.mark.parametrize("payload", [
        {"date": "2033-04-07", "type": "Tatil"},
        {"date": "2033/04/07", "type": "Raporlu"},
        {"date": "bad", "type": "Raporlu"},
        {"date": "2033-04-07", "type": "Yıllık izin", "staff_id": ""},
    ])
    def test_leave_invalid_422(self, payload):
        body = {"staff_id": created["staff"][0], **payload}
        assert requests.post(f"{API}/leaves", json=body).status_code == 422


# ---------- Advances + payroll ----------
class TestAdvancesPayroll:
    def test_payroll_with_advance_and_leave(self):
        s = post("staff", {"name": f"TEST_Pay_{TAG}", "hourly_wage": 100})
        post("shifts", {"staff_id": s["id"], "date": "2033-05-03", "start": "09:00", "end": "17:00"})
        post("leaves", {"staff_id": s["id"], "date": "2033-05-04", "type": "Yıllık izin"})
        a = post("advances", {"staff_id": s["id"], "date": "2033-05-10", "amount": 300, "note": "TEST_avans"})
        post("advances", {"staff_id": s["id"], "date": "2033-06-01", "amount": 999})
        post("advances", {"staff_id": s["id"], "date": "2033-04-30", "amount": 111})
        post("leaves", {"staff_id": s["id"], "date": "2033-06-02", "type": "Raporlu"})
        data = requests.get(f"{API}/payroll", params={"month": "2033-05"}).json()
        r = row_for(data, s["id"])
        assert r["total_pay"] == 800 and r["advance_total"] == 300 and r["net_pay"] == 500 and r["leave_days"] == 1
        assert [x["id"] for x in r["advances"]] == [a["id"]]
        for k in ("total_pay", "advance_total", "net_pay", "leave_days"):
            assert abs(data["totals"][k] - sum(x[k] for x in data["rows"])) < 0.01
        dash = requests.get(f"{API}/dashboard").json()
        assert any(x["id"] == a["id"] for x in dash["advances"])

    @pytest.mark.parametrize("amount", [0, -50])
    def test_advance_amount_invalid(self, amount):
        r = requests.post(f"{API}/advances", json={"staff_id": created["staff"][0], "date": "2033-05-10", "amount": amount})
        assert r.status_code == 422

    def test_advance_missing_amount_and_bad_date(self):
        assert requests.post(f"{API}/advances", json={"staff_id": created["staff"][0], "date": "2033-05-10"}).status_code == 422
        assert requests.post(f"{API}/advances", json={"staff_id": created["staff"][0], "date": "x", "amount": 5}).status_code == 422

    def test_export_sheets(self):
        r = requests.get(f"{API}/payroll/export", params={"month": "2033-05"})
        assert r.status_code == 200
        wb = load_workbook(io.BytesIO(r.content))
        assert wb.sheetnames == ["Maaş Özeti", "Vardiya Detayı", "Avanslar"]
        rows = [[c.value for c in row] for row in wb["Maaş Özeti"].iter_rows()]
        hdr = next(x for x in rows if x and x[0] == "Personel")
        assert "Avans" in hdr and "Net ödenecek" in hdr and "İzin günü" in hdr
        mine = next(x for x in rows if x[0] == f"TEST_Pay_{TAG}")
        assert mine[8:] == [800, 300, 500, 1]
        adv = [[c.value for c in row] for row in wb["Avanslar"].iter_rows()]
        assert [f"TEST_Pay_{TAG}", "10.05.2033", 300, "TEST_avans"] in adv
        assert not any(x[2] in (999, 111) for x in adv[1:] if x[0] == f"TEST_Pay_{TAG}")


# ---------- Staff cascade delete ----------
class TestCascade:
    def test_delete_staff_removes_related(self):
        s = requests.post(f"{API}/staff", json={"name": f"TEST_Del_{TAG}"}).json()
        sh = requests.post(f"{API}/shifts", json={"staff_id": s["id"], "date": "2033-07-04"}).json()
        lv = requests.post(f"{API}/leaves", json={"staff_id": s["id"], "date": "2033-07-05"}).json()
        ad = requests.post(f"{API}/advances", json={"staff_id": s["id"], "date": "2033-07-05", "amount": 10}).json()
        assert requests.delete(f"{API}/staff/{s['id']}").status_code == 200
        dash = requests.get(f"{API}/dashboard").json()
        assert not any(x["id"] == sh["id"] for x in dash["shifts"])
        assert not any(x["id"] == lv["id"] for x in dash["leaves"])
        assert not any(x["id"] == ad["id"] for x in dash["advances"])


# ---------- Orders ----------
class TestOrders:
    def test_orders_crud_toggle(self):
        payload = {"supplier": f"TEST_Sup_{TAG}", "phone": "05550000009", "channel": "WhatsApp",
                   "items": [{"name": "Domates", "unit": "kg", "quantity": 5, "unit_price": 20}], "estimated_total": 100, "status": "Gönderildi"}
        o = post("orders", payload)
        assert o["supplier"] == payload["supplier"] and o["items"][0]["quantity"] == 5 and o["estimated_total"] == 100
        lst = requests.get(f"{API}/orders").json()
        assert lst[0]["id"] == o["id"]  # newest first
        r = requests.put(f"{API}/orders/{o['id']}", json={**o, "status": "Teslim alındı"})
        assert r.status_code == 200 and r.json()["status"] == "Teslim alındı"
        got = next(x for x in requests.get(f"{API}/orders").json() if x["id"] == o["id"])
        assert got["status"] == "Teslim alındı" and got["created_at"] == o["created_at"]
        r = requests.put(f"{API}/orders/{o['id']}", json={**o, "status": "Gönderildi"})
        assert r.json()["status"] == "Gönderildi"
        assert requests.delete(f"{API}/orders/{o['id']}").status_code == 200
        assert not any(x["id"] == o["id"] for x in requests.get(f"{API}/orders").json())

    def test_order_missing_supplier_422(self):
        assert requests.post(f"{API}/orders", json={"items": []}).status_code == 422
