# Iteration 17: multi-restaurant scoping, tables, tips, attendance/clock, staff restaurant binding, summary, product costs, regressions.
# Run with: pytest tests/test_iteration17_multi_restaurant.py -n 0 -v   (tests are ordered and share state)
import os
import pytest
import requests

from conftest import get_token, ADMIN_EMAIL, MEMBER_EMAIL

BASE = open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split()[0].rstrip("/") + "/api"
FL, ET, DU = "florya-tasfirin", "etiler-marmaris", "durumtir"
DAY = "2025-03-12"  # past date used for tips/attendance/shift distribution + payroll 2025-03
S = {}  # shared state
CLEAN = {"sales": [], "products": [], "inventory": [], "tables": [], "tips": [], "attendance": [], "shifts": [], "staff": []}


def adm(rid):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {get_token(ADMIN_EMAIL)[1]}", "X-Restaurant": rid})
    return s


def staff_s(rid_header=FL):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {get_token(MEMBER_EMAIL)[1]}", "X-Restaurant": rid_header})
    return s


def ids(resp):
    return {x["id"] for x in resp.json()}


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    for rid, coll, i in CLEAN_ORDER:
        r = adm(rid).delete(f"{BASE}/{coll}/{i}")
        print("cleanup", coll, i, r.status_code)
    # restore member assignment
    if "member_uid" in S:
        a = adm(FL).patch(f"{BASE}/users/{S['member_uid']}/assignment", json={"restaurant_id": S.get("orig_rid") or FL, "staff_id": ""})
        print("restore member", a.status_code)


CLEAN_ORDER = []  # (restaurant, collection, id) deleted in reverse creation order (appended at front)


def track(rid, coll, i):
    CLEAN_ORDER.insert(0, (rid, coll, i))


# --- restaurant header handling ---
def test_invalid_restaurant_400():
    r = adm("nowhere").get(f"{BASE}/inventory")
    assert r.status_code == 400


def test_me_has_restaurants():
    d = adm(FL).get(f"{BASE}/me").json()
    assert [x["id"] for x in d["restaurants"]] == [FL, ET, DU]
    assert "restaurant_id" in d and "restaurant_name" in d and "staff_id" in d


# --- isolation + all union ---
def test_inventory_isolation_and_all_union():
    a = adm(FL).post(f"{BASE}/inventory", json={"name": "TEST_Kıyma İç", "quantity": 20, "unit": "kg", "minimum": 1, "unit_cost": 10})
    assert a.status_code == 200, a.text
    S["inv_fl"] = a.json()["id"]; track(FL, "inventory", S["inv_fl"])
    b = adm(ET).post(f"{BASE}/inventory", json={"name": "TEST_KIYMA İÇ", "quantity": 10, "unit": "kg", "minimum": 1, "unit_cost": 20})
    assert b.status_code == 200, b.text
    S["inv_et"] = b.json()["id"]; track(ET, "inventory", S["inv_et"])
    fl, et, du, al = (ids(adm(x).get(f"{BASE}/inventory")) for x in (FL, ET, DU, "all"))
    assert S["inv_fl"] in fl and S["inv_fl"] not in et and S["inv_fl"] not in du
    assert S["inv_et"] in et and S["inv_et"] not in fl
    assert {S["inv_fl"], S["inv_et"]} <= al
    # cross-restaurant direct access must 404
    assert adm(ET).put(f"{BASE}/inventory/{S['inv_fl']}", json={"name": "x", "quantity": 1, "unit": "kg"}).status_code == 404
    assert adm(ET).delete(f"{BASE}/inventory/{S['inv_fl']}").status_code == 404


def test_all_mode_writes_blocked():
    s = adm("all")
    for path, body in (("sales", {"product_name": "TEST_x", "quantity": 1, "amount": 1}), ("tables", {"name": "TEST_T"}),
                       ("inventory", {"name": "TEST_all", "quantity": 1, "unit": "kg"})):
        r = s.post(f"{BASE}/{path}", json=body)
        assert r.status_code == 400, (path, r.status_code, r.text)
        assert "restoran seçin" in r.json()["detail"]
    assert s.delete(f"{BASE}/inventory/{S['inv_fl']}").status_code == 400


def test_products_shared_and_all_mode_create():
    r = adm("all").post(f"{BASE}/products", json={"name": "TEST_Kebap17", "category": "TEST", "price": 100,
                                                  "recipe": [{"inventory_id": S["inv_fl"], "amount": 0.5}]})
    assert r.status_code == 200, r.text
    p = r.json(); S["prod"] = p["id"]; track(FL, "products", p["id"])
    assert p["cost"] == pytest.approx(7.5)  # avg(10,20) * 0.5
    sets = [ids(adm(x).get(f"{BASE}/products")) for x in (FL, ET, DU, "all")]
    assert all(st == sets[0] for st in sets) and S["prod"] in sets[0]


# --- cross-restaurant recipe deduction ---
def test_sale_in_other_restaurant_deducts_local_same_name():
    r = adm(ET).post(f"{BASE}/sales", json={"product_id": S["prod"], "product_name": "TEST_Kebap17", "quantity": 2, "unit_price": 100, "amount": 200, "payment": "Nakit"})
    assert r.status_code == 200, r.text
    sale = r.json(); S["sale_et"] = sale["id"]
    assert sale["unit_cost"] == pytest.approx(10)  # 0.5 * etiler 20
    et = {i["id"]: i for i in adm(ET).get(f"{BASE}/inventory").json()}
    fl = {i["id"]: i for i in adm(FL).get(f"{BASE}/inventory").json()}
    assert et[S["inv_et"]]["quantity"] == pytest.approx(9)
    assert fl[S["inv_fl"]]["quantity"] == pytest.approx(20)
    assert S["sale_et"] in ids(adm(ET).get(f"{BASE}/sales")) and S["sale_et"] not in ids(adm(FL).get(f"{BASE}/sales"))


def test_sale_delete_reverses_stock():
    assert adm(ET).delete(f"{BASE}/sales/{S['sale_et']}").status_code == 200
    et = {i["id"]: i for i in adm(ET).get(f"{BASE}/inventory").json()}
    assert et[S["inv_et"]]["quantity"] == pytest.approx(10)


# --- tables ---
def test_tables_crud_and_order_flow():
    s = adm(ET)
    t = s.post(f"{BASE}/tables", json={"name": "TEST_M1", "seats": 2})
    assert t.status_code == 200, t.text
    S["table"] = t.json()["id"]; track(ET, "tables", S["table"])
    assert S["table"] not in ids(adm(FL).get(f"{BASE}/tables"))
    u = s.put(f"{BASE}/tables/{S['table']}", json={"name": "TEST_M1", "seats": 6})
    assert u.status_code == 200 and u.json()["seats"] == 6
    v = s.get(f"{BASE}/tables-view").json()
    row = next(x for x in v["tables"] if x["id"] == S["table"])
    assert row["order"] is None and any(p["id"] == S["prod"] for p in v["products"])
    # neg on empty -> 422
    assert s.post(f"{BASE}/tables/{S['table']}/items", json={"product_id": S["prod"], "quantity": -1}).status_code == 422
    o = s.post(f"{BASE}/tables/{S['table']}/items", json={"product_id": S["prod"], "quantity": 3}).json()
    assert o["total"] == 300
    o = s.post(f"{BASE}/tables/{S['table']}/items", json={"product_id": S["prod"], "quantity": -1}).json()
    assert o["items"][0]["quantity"] == 2 and o["total"] == 200
    adm_fl_view = adm(FL).get(f"{BASE}/tables-view").json()
    assert all(x["id"] != S["table"] for x in adm_fl_view["tables"])


def test_table_close_creates_sales_tip_and_stock():
    s = adm(ET)
    before = {i["id"]: i for i in s.get(f"{BASE}/inventory").json()}[S["inv_et"]]["quantity"]
    assert s.post(f"{BASE}/tables/{S['table']}/close", json={"payment": "Bitcoin"}).status_code == 422
    r = s.post(f"{BASE}/tables/{S['table']}/close", json={"payment": "Kart", "tip": 15})
    assert r.status_code == 200, r.text
    assert r.json()["sales"] == 1 and r.json()["total"] == 200
    sales = [x for x in s.get(f"{BASE}/sales").json() if x.get("product_id") == S["prod"]]
    assert len(sales) == 1 and sales[0]["payment"] == "Kart" and sales[0]["amount"] == 200 and sales[0]["channel"] == "Salon"
    S["table_sale"] = sales[0]["id"]
    after = {i["id"]: i for i in s.get(f"{BASE}/inventory").json()}[S["inv_et"]]["quantity"]
    assert after == pytest.approx(before - 1)
    tips = [x for x in s.get(f"{BASE}/tips").json() if "TEST_M1" in x.get("note", "")]
    assert tips and tips[0]["amount"] == 15
    for t in tips:
        track(ET, "tips", t["id"])
    row = next(x for x in s.get(f"{BASE}/tables-view").json()["tables"] if x["id"] == S["table"])
    assert row["order"] is None
    # close again -> 422
    assert s.post(f"{BASE}/tables/{S['table']}/close", json={"payment": "Nakit"}).status_code == 422
    assert s.delete(f"{BASE}/sales/{S['table_sale']}").status_code == 200


def test_table_cancel():
    s = adm(ET)
    s.post(f"{BASE}/tables/{S['table']}/items", json={"product_id": S["prod"], "quantity": 1})
    before = len(s.get(f"{BASE}/sales").json())
    assert s.post(f"{BASE}/tables/{S['table']}/cancel").status_code == 200
    assert len(s.get(f"{BASE}/sales").json()) == before
    assert s.post(f"{BASE}/tables/{S['table']}/cancel").status_code == 404


# --- staff / tips distribution / attendance ---
def test_tips_distribution_by_hours():
    s = adm(ET)
    a = s.post(f"{BASE}/staff", json={"name": "TEST_Ali17", "task": "Garson", "hourly_wage": 100}).json()
    b = s.post(f"{BASE}/staff", json={"name": "TEST_Veli17", "task": "Garson", "hourly_wage": 100}).json()
    S["st_a"], S["st_b"] = a["id"], b["id"]; track(ET, "staff", a["id"]); track(ET, "staff", b["id"])
    assert S["st_a"] not in ids(adm(FL).get(f"{BASE}/staff"))
    at = s.post(f"{BASE}/attendance", json={"staff_id": S["st_a"], "date": DAY, "start": "10:00", "end": "16:00"})
    assert at.status_code == 200, at.text
    S["att"] = at.json()["id"]; track(ET, "attendance", S["att"])
    # a planned shift for A that must be ignored (attendance wins)
    sh_a = s.post(f"{BASE}/shifts", json={"staff_id": S["st_a"], "date": DAY, "start": "08:00", "end": "20:00"}).json(); track(ET, "shifts", sh_a["id"])
    sh_b = s.post(f"{BASE}/shifts", json={"staff_id": S["st_b"], "date": DAY, "start": "10:00", "end": "13:00"})
    assert sh_b.status_code == 200, sh_b.text; track(ET, "shifts", sh_b.json()["id"])
    tip = s.post(f"{BASE}/tips", json={"date": DAY, "amount": 90, "note": "TEST_tip"}).json(); track(ET, "tips", tip["id"])
    u = s.put(f"{BASE}/tips/{tip['id']}", json={"date": DAY, "amount": 90, "note": "TEST_tip2"})
    assert u.status_code == 200 and u.json()["note"] == "TEST_tip2"
    d = s.get(f"{BASE}/tips/distribution", params={"date": DAY}).json()
    assert d["total"] == 90
    rows = {r["staff_id"]: r for r in d["rows"]}
    assert rows[S["st_a"]]["hours"] == 6 and rows[S["st_a"]]["share"] == 60 and rows[S["st_a"]]["source"] == "Giriş-çıkış"
    assert rows[S["st_b"]]["hours"] == 3 and rows[S["st_b"]]["share"] == 30
    assert adm(FL).get(f"{BASE}/tips/distribution", params={"date": DAY}).json()["total"] == 0


def test_payroll_uses_attendance():
    rows = {r["staff_id"]: r for r in adm(ET).get(f"{BASE}/payroll", params={"month": "2025-03"}).json()["rows"]}
    assert rows[S["st_a"]]["hours_source"] == "Giriş-çıkış"
    assert rows[S["st_a"]]["regular_hours"] + rows[S["st_a"]]["overtime_hours"] == pytest.approx(6)
    assert rows[S["st_b"]]["hours_source"] == "Vardiya planı" and rows[S["st_b"]]["regular_hours"] == pytest.approx(3)


def test_assignment_validation_and_unlinked_clock():
    uid = get_token(MEMBER_EMAIL)[0]
    S["member_uid"] = uid
    S["orig_rid"] = staff_s().get(f"{BASE}/me").json().get("restaurant_id")
    s = adm(FL)
    assert s.patch(f"{BASE}/users/{uid}/assignment", json={"restaurant_id": FL, "staff_id": S["st_a"]}).status_code == 422
    assert s.patch(f"{BASE}/users/{uid}/assignment", json={"restaurant_id": "bad", "staff_id": ""}).status_code == 422
    assert s.patch(f"{BASE}/users/{uid}/assignment", json={"restaurant_id": ET, "staff_id": ""}).status_code == 200
    assert staff_s().post(f"{BASE}/attendance/clock").status_code == 409
    assert staff_s().get(f"{BASE}/attendance/me").json() == {"linked": False}


def test_staff_scope_and_clock():
    uid = S["member_uid"]
    r = adm(FL).patch(f"{BASE}/users/{uid}/assignment", json={"restaurant_id": ET, "staff_id": S["st_a"]})
    assert r.status_code == 200
    st = staff_s(FL)  # header says florya, must be ignored
    me = st.get(f"{BASE}/me").json()
    assert me["restaurant_id"] == ET and me["restaurant_name"] == "Etiler Marmaris" and me["staff_id"] == S["st_a"]
    v = st.get(f"{BASE}/tables-view").json()
    assert any(t["id"] == S["table"] for t in v["tables"])
    assert st.get(f"{BASE}/dashboard").status_code == 403
    assert st.get(f"{BASE}/tips").status_code == 403
    assert st.get(f"{BASE}/restaurants/summary").status_code == 403
    c1 = st.post(f"{BASE}/attendance/clock")
    assert c1.status_code == 200 and c1.json()["status"] == "in", c1.text
    m = st.get(f"{BASE}/attendance/me").json()
    assert m["linked"] and m["open"] and m["name"] == "TEST_Ali17"
    track(ET, "attendance", m["open"]["id"])
    c2 = st.post(f"{BASE}/attendance/clock")
    assert c2.status_code == 200 and c2.json()["status"] == "out"
    assert st.get(f"{BASE}/attendance/me").json()["open"] is None
    att = [a for a in adm(ET).get(f"{BASE}/attendance").json() if a["id"] == m["open"]["id"]]
    assert att and att[0]["end"]


def test_staff_table_flow_and_sale_in_own_restaurant():
    st = staff_s(FL)
    assert st.post(f"{BASE}/tables/{S['table']}/items", json={"product_id": S["prod"], "quantity": 1}).status_code == 200
    r = st.post(f"{BASE}/tables/{S['table']}/close", json={"payment": "Nakit", "tip": 0})
    assert r.status_code == 200, r.text
    sales = [x for x in adm(ET).get(f"{BASE}/sales").json() if x.get("product_id") == S["prod"]]
    assert len(sales) == 1 and sales[0]["created_by"] == MEMBER_EMAIL
    assert adm(ET).delete(f"{BASE}/sales/{sales[0]['id']}").status_code == 200
    # staff POST /api/sales goes to etiler
    r = st.post(f"{BASE}/sales", json={"product_id": S["prod"], "product_name": "", "quantity": 1, "amount": 0})
    assert r.status_code == 200, r.text
    assert r.json()["id"] in ids(adm(ET).get(f"{BASE}/sales"))
    assert r.json()["id"] not in ids(adm(FL).get(f"{BASE}/sales"))
    assert adm(ET).delete(f"{BASE}/sales/{r.json()['id']}").status_code == 200
    # staff inventory count in own restaurant only
    assert st.post(f"{BASE}/inventory/{S['inv_et']}/count", json={"quantity": 10}).status_code == 200
    assert st.post(f"{BASE}/inventory/{S['inv_fl']}/count", json={"quantity": 5}).status_code == 404


# --- summary & product costs ---
def test_restaurants_summary():
    rows = adm(FL).get(f"{BASE}/restaurants/summary").json()
    assert [r["id"] for r in rows] == [FL, ET, DU]
    for k in ("today_revenue", "month_revenue", "today_profit", "month_profit", "low_stock", "open_tables"):
        assert k in rows[0]


def test_product_costs():
    d = adm(FL).get(f"{BASE}/product-costs").json()
    row = next(p for p in d["products"] if p["id"] == S["prod"])
    pr = row["per_restaurant"]
    assert pr[FL]["cost"] == pytest.approx(5) and pr[ET]["cost"] == pytest.approx(10)
    assert pr[DU]["missing"] and pr[DU]["margin"] is None
    assert pr[FL]["margin"] is not None
    assert row["lines"][0]["per_restaurant"][DU] is None


# --- regressions ---
def test_cash_reconciliation_per_restaurant():
    for rid in (FL, ET, "all"):
        r = adm(rid).get(f"{BASE}/cash/reconciliation")
        assert r.status_code == 200, (rid, r.text)


def test_public_leave_link_approve_creates_leaves_in_staff_restaurant():
    tok = adm(ET).post(f"{BASE}/staff/{S['st_b']}/request-link").json()["token"]
    pub = requests.get(f"{BASE}/public/leave/{tok}", headers={"X-No-Auth": "1"})
    assert pub.status_code == 200 and pub.json()["name"] == "TEST_Veli17"
    from datetime import date, timedelta
    d = (date.today() + timedelta(days=40)).isoformat()
    p = requests.post(f"{BASE}/public/leave/{tok}", json={"start": d, "end": d, "type": "Yıllık izin", "note": "TEST"}, headers={"X-No-Auth": "1"})
    assert p.status_code == 200, p.text
    req_id = p.json()["id"]
    assert req_id in {x["id"] for x in adm(ET).get(f"{BASE}/dashboard").json()["leave_requests"]}
    assert req_id not in {x["id"] for x in adm(FL).get(f"{BASE}/dashboard").json()["leave_requests"]}
    a = adm(ET).post(f"{BASE}/leave-requests/{req_id}/approve")
    assert a.status_code == 200 and a.json()["created"] == 1
    assert any(l["staff_id"] == S["st_b"] for l in adm(ET).get(f"{BASE}/leaves").json())
    assert not any(l["staff_id"] == S["st_b"] for l in adm(FL).get(f"{BASE}/leaves").json())
