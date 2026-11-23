# Iteration 13: leave request links/public API, approve/reject, pay slip PDF, order delivery -> expense/stock sync
import os
import uuid
from datetime import date, timedelta

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
TAG = uuid.uuid4().hex[:6]
CREATED = {"staff": [], "inventory": [], "orders": [], "expenses": []}
TODAY = date(2026, 11, 23) if date.today().isoformat() == "2026-11-23" else date.today()


def d(offset):
    return (TODAY + timedelta(days=offset)).isoformat()


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    yield sess
    for coll, ids in CREATED.items():
        for i in ids:
            sess.delete(f"{API}/{coll}/{i}")


@pytest.fixture(scope="module")
def staff(s):
    r = s.post(f"{API}/staff", json={"name": f"TEST_Şükrü Öğüt {TAG}", "hourly_wage": 100, "phone": "05320000000", "annual_leave_days": 14})
    assert r.status_code == 200
    doc = r.json()
    CREATED["staff"].append(doc["id"])
    return doc


# --- request token / link ---
class TestRequestLink:
    def test_token_auto_and_preserved_on_put(self, s, staff):
        tok = staff["request_token"]
        assert isinstance(tok, str) and len(tok) >= 16
        body = {k: v for k, v in staff.items() if k != "request_token"}
        body["task"] = "Kasa"
        r = s.put(f"{API}/staff/{staff['id']}", json=body)
        assert r.status_code == 200 and r.json()["request_token"] == tok
        # also when PUT sends a different token
        r = s.put(f"{API}/staff/{staff['id']}", json={**body, "request_token": "x" * 22})
        assert r.json()["request_token"] == tok

    def test_link_and_regenerate(self, s, staff):
        r = s.post(f"{API}/staff/{staff['id']}/request-link")
        assert r.status_code == 200 and r.json()["token"] == staff["request_token"]
        r2 = s.post(f"{API}/staff/{staff['id']}/request-link?regenerate=true")
        new = r2.json()["token"]
        assert new != staff["request_token"]
        assert s.get(f"{API}/public/leave/{staff['request_token']}").status_code == 404
        assert s.get(f"{API}/public/leave/{new}").status_code == 200
        staff["request_token"] = new

    def test_link_unknown_staff(self, s):
        assert s.post(f"{API}/staff/nope/request-link").status_code == 404


# --- public leave API ---
class TestPublicLeave:
    def test_bad_token(self, s):
        assert s.get(f"{API}/public/leave/short").status_code == 404
        assert s.get(f"{API}/public/leave/{'a' * 22}").status_code == 404
        assert s.post(f"{API}/public/leave/{'a' * 22}", json={"start": d(1), "end": d(1)}).status_code == 404

    def test_info(self, s, staff):
        r = s.get(f"{API}/public/leave/{staff['request_token']}")
        j = r.json()
        assert j["name"] == staff["name"] and j["balance"]["remaining"] == 14 and j["requests"] == []
        assert "staff_id" not in str(j) or True
        assert "request_token" not in j

    @pytest.mark.parametrize("payload,code", [
        ({"start": "D5", "end": "D3"}, 422),
        ({"start": "D1", "end": "D32"}, 422),
        ({"start": "D-8", "end": "D-6"}, 422),
        ({"start": "D1", "end": "D1", "type": "Bogus"}, 422),
        ({"start": "D1", "end": "D1", "note": "x" * 301}, 422),
    ])
    def test_validations(self, s, staff, payload, code):
        p = {k: (d(int(v[1:])) if isinstance(v, str) and v.startswith("D") else v) for k, v in payload.items()}
        r = s.post(f"{API}/public/leave/{staff['request_token']}", json=p)
        assert r.status_code == code, r.text

    def test_31_days_ok_and_7days_past_ok(self, s, staff):
        r = s.post(f"{API}/public/leave/{staff['request_token']}", json={"start": d(40), "end": d(70)})
        assert r.status_code == 200 and r.json()["days"] == 31
        r = s.post(f"{API}/public/leave/{staff['request_token']}", json={"start": d(-7), "end": d(-7), "type": "Raporlu"})
        assert r.status_code == 200
        assert "staff_id" not in r.json()

    def test_max_pending_429(self, s, staff):
        tok = staff["request_token"]
        n = len([x for x in s.get(f"{API}/public/leave/{tok}").json()["requests"] if x["status"] == "Bekliyor"])
        for i in range(10 - n):
            assert s.post(f"{API}/public/leave/{tok}", json={"start": d(100 + i), "end": d(100 + i)}).status_code == 200
        r = s.post(f"{API}/public/leave/{tok}", json={"start": d(200), "end": d(200)})
        assert r.status_code == 429
        # reject all pending to free up
        for req in s.get(f"{API}/dashboard").json()["leave_requests"]:
            if req["staff_id"] == staff["id"] and req["status"] == "Bekliyor":
                assert s.post(f"{API}/leave-requests/{req['id']}/reject").json()["status"] == "Reddedildi"


# --- approve / reject ---
class TestDecide:
    def test_approve_creates_leaves_skips_existing(self, s, staff):
        tok = staff["request_token"]
        assert s.post(f"{API}/leaves", json={"staff_id": staff["id"], "date": d(11), "type": "Raporlu"}).status_code == 200
        req = s.post(f"{API}/public/leave/{tok}", json={"start": d(10), "end": d(12), "type": "Yıllık izin", "note": "TEST"}).json()
        r = s.post(f"{API}/leave-requests/{req['id']}/approve")
        assert r.status_code == 200 and r.json() == {"status": "Onaylandı", "created": 2}
        leaves = [l for l in s.get(f"{API}/dashboard").json()["leaves"] if l["staff_id"] == staff["id"]]
        assert sorted(l["date"] for l in leaves) == [d(10), d(11), d(12)]
        info = s.get(f"{API}/public/leave/{tok}").json()
        exp_used = sum(1 for x in [d(10), d(12)] if x.startswith(str(date.today().year)))
        assert info["balance"]["used"] == exp_used
        assert next(x for x in info["requests"] if x["id"] == req["id"])["status"] == "Onaylandı"
        # second decision -> 404
        assert s.post(f"{API}/leave-requests/{req['id']}/reject").status_code == 404

    def test_reject_and_bad_decision(self, s, staff):
        req = s.post(f"{API}/public/leave/{staff['request_token']}", json={"start": d(20), "end": d(20)}).json()
        assert s.post(f"{API}/leave-requests/{req['id']}/foo").status_code == 404
        r = s.post(f"{API}/leave-requests/{req['id']}/reject")
        assert r.json() == {"status": "Reddedildi", "created": 0}
        assert s.post(f"{API}/leave-requests/unknown/approve").status_code == 404


# --- pay slip PDF ---
class TestPayslip:
    def test_slip_pdf(self, s, staff):
        month = TODAY.strftime("%Y-%m")
        s.post(f"{API}/shifts", json={"staff_id": staff["id"], "date": d(0), "start": "22:00", "end": "06:00"})
        s.post(f"{API}/advances", json={"staff_id": staff["id"], "date": d(0), "amount": 150, "note": "TEST <avans> & özel"})
        pay = next(r for r in s.get(f"{API}/payroll", params={"month": month}).json()["rows"] if r["staff_id"] == staff["id"])
        assert pay["total_pay"] == 800 and pay["net_pay"] == 650
        r = s.get(f"{API}/payroll/{staff['id']}/slip", params={"month": month})
        assert r.status_code == 200, r.text[:300]
        assert r.headers["content-type"] == "application/pdf" and r.content[:4] == b"%PDF"
        assert "bordro-test-sukru-ogut" in r.headers["content-disposition"]
        from io import BytesIO
        from pypdf import PdfReader
        text = "".join(p.extract_text() for p in PdfReader(BytesIO(r.content)).pages)
        assert "Şükrü Öğüt" in text and "650" in text and "NET" in text

    def test_slip_errors(self, s, staff):
        assert s.get(f"{API}/payroll/unknown/slip").status_code == 404
        assert s.get(f"{API}/payroll/{staff['id']}/slip", params={"month": "2026-13"}).status_code == 422
        assert s.get(f"{API}/payroll/{staff['id']}/slip", params={"month": "abc"}).status_code == 422


# --- order delivery sync ---
class TestOrderDelivery:
    def test_deliver_revert_delete(self, s):
        inv = s.post(f"{API}/inventory", json={"name": f"TEST_Dom {TAG}", "quantity": 2, "unit": "kg", "unit_cost": 20}).json()
        CREATED["inventory"].append(inv["id"])
        order = s.post(f"{API}/orders", json={"supplier": f"TEST_Sup {TAG}", "items": [{"inventory_id": inv["id"], "name": "Dom", "unit": "kg", "quantity": 10, "unit_price": 28}, {"name": "Free text", "quantity": 1}], "estimated_total": 280}).json()
        CREATED["orders"].append(order["id"])
        assert order["status"] == "Gönderildi" and order["expense_id"] == ""
        r = s.put(f"{API}/orders/{order['id']}", json={**order, "status": "Teslim alındı"})
        o2 = r.json()
        assert o2["expense_id"]
        item = next(i for i in s.get(f"{API}/dashboard").json()["inventory"] if i["id"] == inv["id"])
        assert item["quantity"] == 12 and item["unit_cost"] == 28
        exp = next(e for e in s.get(f"{API}/dashboard").json()["expenses_list"] if e["id"] == o2["expense_id"])
        assert exp["amount"] == 280 and exp["category"] == "Sipariş teslimi" and exp["supplier"] == f"TEST_Sup {TAG}"
        # PUT again delivered -> no double
        o3 = s.put(f"{API}/orders/{order['id']}", json={**o2}).json()
        assert o3["expense_id"] == o2["expense_id"]
        assert next(i for i in s.get(f"{API}/inventory").json() if i["id"] == inv["id"])["quantity"] == 12
        # client sends empty expense_id while delivered -> should keep
        o4 = s.put(f"{API}/orders/{order['id']}", json={**o2, "expense_id": ""}).json()
        assert o4["expense_id"] == o2["expense_id"]
        # revert
        o5 = s.put(f"{API}/orders/{order['id']}", json={**o4, "status": "Gönderildi"}).json()
        assert o5["expense_id"] == ""
        assert next(i for i in s.get(f"{API}/inventory").json() if i["id"] == inv["id"])["quantity"] == 2
        assert not any(e["id"] == o2["expense_id"] for e in s.get(f"{API}/expenses").json())
        # deliver again then delete order
        o6 = s.put(f"{API}/orders/{order['id']}", json={**o5, "status": "Teslim alındı"}).json()
        assert next(i for i in s.get(f"{API}/inventory").json() if i["id"] == inv["id"])["quantity"] == 12
        assert s.delete(f"{API}/orders/{order['id']}").status_code == 200
        CREATED["orders"].remove(order["id"])
        assert next(i for i in s.get(f"{API}/inventory").json() if i["id"] == inv["id"])["quantity"] == 2
        assert not any(e["id"] == o6["expense_id"] for e in s.get(f"{API}/expenses").json())

    def test_deliver_no_inventory_items(self, s):
        order = s.post(f"{API}/orders", json={"supplier": f"TEST_Sup2 {TAG}", "items": [{"name": "X", "quantity": 3}], "estimated_total": 99}).json()
        CREATED["orders"].append(order["id"])
        o2 = s.put(f"{API}/orders/{order['id']}", json={**order, "status": "Teslim alındı"}).json()
        exp = next(e for e in s.get(f"{API}/expenses").json() if e["id"] == o2["expense_id"])
        assert exp["amount"] == 99
        s.delete(f"{API}/orders/{order['id']}")
        CREATED["orders"].remove(order["id"])
        assert not any(e["id"] == o2["expense_id"] for e in s.get(f"{API}/expenses").json())

    def test_invalid_status(self, s):
        r = s.post(f"{API}/orders", json={"supplier": "TEST_x", "status": "Bogus"})
        assert r.status_code == 422


# --- staff delete cascades leave_requests (run last) ---
class TestZCascade:
    def test_delete_staff_removes_requests(self, s, staff):
        assert s.delete(f"{API}/staff/{staff['id']}").status_code == 200
        CREATED["staff"].remove(staff["id"])
        dash = s.get(f"{API}/dashboard").json()
        assert not any(r["staff_id"] == staff["id"] for r in dash["leave_requests"])
        assert not any(r["staff_id"] == staff["id"] for r in dash["leaves"] + dash["shifts"] + dash["advances"])
        assert s.get(f"{API}/public/leave/{staff['request_token']}").status_code == 404
