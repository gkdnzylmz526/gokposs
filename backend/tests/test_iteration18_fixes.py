# Iteration 18: retest of it17 fixes - table delete 409, all-mode staff write guard, attendance validation, staff delete cascade,
# table close/cancel effects (sales/stock/staff-today). Restores member role + assignment at teardown.
# Run with: pytest tests/test_iteration18_fixes.py -n 0 -v   (ordered, shared state)
import pytest
import requests

from conftest import get_token, ADMIN_EMAIL, MEMBER_EMAIL

BASE = open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split()[0].rstrip("/") + "/api"
FL, ET, DU = "florya-tasfirin", "etiler-marmaris", "durumtir"
DAY = "2025-03-13"
S = {}
CLEAN = []  # (rid, coll, id), deleted in reverse order


def adm(rid):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {get_token(ADMIN_EMAIL)[1]}", "X-Restaurant": rid})
    return s


def member_s():
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {get_token(MEMBER_EMAIL)[1]}", "X-Restaurant": FL})
    return s


def track(rid, coll, i):
    CLEAN.insert(0, (rid, coll, i))


@pytest.fixture(scope="module", autouse=True)
def setup_and_restore():
    uid = get_token(MEMBER_EMAIL)[0]
    users = adm(FL).get(f"{BASE}/users").json()["users"]
    me = next(u for u in users if u["user_id"] == uid)
    S["member_uid"], S["orig"] = uid, me
    yield
    for rid, coll, i in CLEAN:
        print("cleanup", coll, i, adm(rid).delete(f"{BASE}/{coll}/{i}").status_code)
    o = S["orig"]
    print("restore role", adm(FL).patch(f"{BASE}/users/{uid}/role", json={"role": o.get("role") or "staff"}).status_code)
    print("restore assignment", adm(FL).patch(f"{BASE}/users/{uid}/assignment",
                                              json={"restaurant_id": o.get("restaurant_id") or FL, "staff_id": o.get("staff_id") or ""}).status_code)


# --- setup data in Etiler ---
def test_setup_data():
    s = adm(ET)
    inv = s.post(f"{BASE}/inventory", json={"name": "TEST_It18_Et", "quantity": 10, "unit": "kg", "minimum": 1, "unit_cost": 40})
    assert inv.status_code == 200, inv.text
    S["inv"] = inv.json()["id"]; track(ET, "inventory", S["inv"])
    p = s.post(f"{BASE}/products", json={"name": "TEST_It18_Kebap", "category": "TEST", "price": 100, "recipe": [{"inventory_id": S["inv"], "amount": 0.5}]})
    assert p.status_code == 200, p.text
    S["prod"] = p.json()["id"]; track(ET, "products", S["prod"])
    t = s.post(f"{BASE}/tables", json={"name": "TEST_It18_M1", "seats": 4})
    assert t.status_code == 200, t.text
    S["table"] = t.json()["id"]; track(ET, "tables", S["table"])
    st = s.post(f"{BASE}/staff", json={"name": "TEST_It18_Garson", "task": "Garson", "hourly_wage": 100})
    assert st.status_code == 200
    S["staff"] = st.json()["id"]; track(ET, "staff", S["staff"])
    fl_st = adm(FL).post(f"{BASE}/staff", json={"name": "TEST_It18_FlGarson", "task": "Garson", "hourly_wage": 100})
    S["staff_fl"] = fl_st.json()["id"]; track(FL, "staff", S["staff_fl"])


# --- DELETE table with open order -> 409 ---
def test_delete_table_with_open_order_409():
    s = adm(ET)
    assert s.post(f"{BASE}/tables/{S['table']}/items", json={"product_id": S["prod"], "quantity": 2}).status_code == 200
    r = s.delete(f"{BASE}/tables/{S['table']}")
    assert r.status_code == 409, r.text
    assert "Masada açık hesap var" in r.json()["detail"]
    assert any(t["id"] == S["table"] for t in s.get(f"{BASE}/tables").json())


def test_delete_table_without_order_ok():
    s = adm(ET)
    t = s.post(f"{BASE}/tables", json={"name": "TEST_It18_Del", "seats": 2}).json()
    assert s.delete(f"{BASE}/tables/{t['id']}").status_code == 200
    assert all(x["id"] != t["id"] for x in s.get(f"{BASE}/tables").json())
    # after cancel the 409 is gone
    t2 = s.post(f"{BASE}/tables", json={"name": "TEST_It18_Del2", "seats": 2}).json()
    s.post(f"{BASE}/tables/{t2['id']}/items", json={"product_id": S["prod"], "quantity": 1})
    assert s.delete(f"{BASE}/tables/{t2['id']}").status_code == 409
    assert s.post(f"{BASE}/tables/{t2['id']}/cancel").status_code == 200
    assert s.delete(f"{BASE}/tables/{t2['id']}").status_code == 200


def test_table_close_creates_sale_and_deducts_stock():
    s = adm(ET)
    r = s.post(f"{BASE}/tables/{S['table']}/close", json={"payment": "Nakit", "tip": 0})
    assert r.status_code == 200, r.text
    sales = [x for x in s.get(f"{BASE}/sales").json() if x.get("product_id") == S["prod"]]
    assert len(sales) == 1 and sales[0]["amount"] == 200
    track(ET, "sales", sales[0]["id"])
    inv = {i["id"]: i for i in s.get(f"{BASE}/inventory").json()}[S["inv"]]
    assert inv["quantity"] == pytest.approx(9)
    d = s.get(f"{BASE}/dashboard").json()
    assert any(x.get("id") == sales[0]["id"] for x in d["sales"])
    # table now deletable state (no open order)
    assert next(t for t in s.get(f"{BASE}/tables-view").json()["tables"] if t["id"] == S["table"])["order"] is None


# --- all-mode staff guard ---
def test_all_mode_staff_put_delete_blocked_request_link_allowed():
    s = adm("all")
    r = s.put(f"{BASE}/staff/{S['staff']}", json={"name": "TEST_hack", "task": "Garson", "hourly_wage": 1})
    assert r.status_code == 400 and "restoran seçin" in r.json()["detail"], r.text
    assert s.delete(f"{BASE}/staff/{S['staff']}").status_code == 400
    assert any(x["id"] == S["staff"] and x["name"] == "TEST_It18_Garson" for x in adm(ET).get(f"{BASE}/staff").json())
    rl = s.post(f"{BASE}/staff/{S['staff']}/request-link")
    assert rl.status_code == 200 and rl.json().get("token"), rl.text
    assert s.post(f"{BASE}/staff", json={"name": "TEST_x", "task": "Garson"}).status_code == 400


# --- attendance validation ---
def test_attendance_unknown_staff_422():
    r = adm(ET).post(f"{BASE}/attendance", json={"staff_id": "nope-123", "date": DAY, "start": "09:00", "end": "17:00"})
    assert r.status_code == 422, r.text


def test_attendance_other_restaurant_staff_422():
    r = adm(ET).post(f"{BASE}/attendance", json={"staff_id": S["staff_fl"], "date": DAY, "start": "09:00", "end": "17:00"})
    assert r.status_code == 422, r.text


def test_attendance_too_long_422_and_overnight_ok():
    s = adm(ET)
    r = s.post(f"{BASE}/attendance", json={"staff_id": S["staff"], "date": DAY, "start": "09:00", "end": "08:00"})
    assert r.status_code == 422, r.text
    ok = s.post(f"{BASE}/attendance", json={"staff_id": S["staff"], "date": DAY, "start": "18:00", "end": "02:00"})
    assert ok.status_code == 200, ok.text
    S["att"] = ok.json()["id"]
    # PUT validation
    assert s.put(f"{BASE}/attendance/{S['att']}", json={"staff_id": S["staff"], "date": DAY, "start": "09:00", "end": "08:30"}).status_code == 422
    assert s.put(f"{BASE}/attendance/{S['att']}", json={"staff_id": "nope-123", "date": DAY, "start": "09:00", "end": "10:00"}).status_code == 422
    assert s.put(f"{BASE}/attendance/{S['att']}", json={"staff_id": S["staff_fl"], "date": DAY, "start": "09:00", "end": "10:00"}).status_code == 422
    u = s.put(f"{BASE}/attendance/{S['att']}", json={"staff_id": S["staff"], "date": DAY, "start": "18:00", "end": "01:00"})
    assert u.status_code == 200 and u.json()["end"] == "01:00"
    att = next(a for a in s.get(f"{BASE}/attendance").json() if a["id"] == S["att"])
    assert att["end"] == "01:00"


# --- staff app: table close shows in staff-today ---
def test_staff_table_close_shows_in_staff_view():
    uid = S["member_uid"]
    assert adm(FL).patch(f"{BASE}/users/{uid}/role", json={"role": "staff"}).status_code == 200
    assert adm(FL).patch(f"{BASE}/users/{uid}/assignment", json={"restaurant_id": ET, "staff_id": S["staff"]}).status_code == 200
    st = member_s()
    assert st.post(f"{BASE}/tables/{S['table']}/items", json={"product_id": S["prod"], "quantity": 1}).status_code == 200
    assert st.delete(f"{BASE}/tables/{S['table']}").status_code == 403
    r = st.post(f"{BASE}/tables/{S['table']}/close", json={"payment": "Kart", "tip": 0})
    assert r.status_code == 200, r.text
    v = st.get(f"{BASE}/staff-view").json()
    sale = next(x for x in adm(ET).get(f"{BASE}/sales").json() if x.get("product_id") == S["prod"] and x.get("created_by") == MEMBER_EMAIL)
    track(ET, "sales", sale["id"])
    blob = str(v)
    assert sale["id"] in blob or "TEST_It18_Kebap" in blob, list(v.keys())
    inv = next(i for i in v.get("inventory", []) if i["id"] == S["inv"])
    assert inv["quantity"] == pytest.approx(8.5)


# --- staff delete cascades attendance ---
def test_staff_delete_cascades_attendance():
    s = adm(ET)
    st = s.post(f"{BASE}/staff", json={"name": "TEST_It18_Cascade", "task": "Garson", "hourly_wage": 100}).json()
    a = s.post(f"{BASE}/attendance", json={"staff_id": st["id"], "date": DAY, "start": "10:00", "end": "12:00"})
    assert a.status_code == 200
    assert s.delete(f"{BASE}/staff/{st['id']}").status_code == 200
    assert all(x["id"] != a.json()["id"] for x in s.get(f"{BASE}/attendance").json())


def test_audit_log_readable_summaries():
    logs = adm(ET).get(f"{BASE}/audit-logs").json()
    logs = logs.get("logs", logs) if isinstance(logs, dict) else logs
    att = [l for l in logs if l["collection"] == "attendance" and l["item_id"] == S["att"]]
    assert att and "18:00" in att[0]["summary"], att[:1]
    tab = [l for l in logs if l["collection"] == "tables" and l["item_id"] == S["table"]]
    assert tab and all("Masa" in l["summary"] for l in tab)
