# Iteration 19: split bill (amount/items/pending), kitchen tickets, stock transfers between restaurants,
# per-restaurant report export + daily email body. Ordered shared state; run with -n 0.
# Restores member role/assignment; cleans TEST_ data incl. kitchen_tickets, stock_transfers, stock_movements.
import asyncio
import io
import os
import sys

import pytest
import requests
from pymongo import MongoClient

from conftest import get_token, ADMIN_EMAIL, MEMBER_EMAIL

BASE = open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split()[0].rstrip("/") + "/api"
FL, ET, DU = "florya-tasfirin", "etiler-marmaris", "durumtir"
ENV = dict(l.strip().split("=", 1) for l in open("/app/backend/.env") if "=" in l)
MDB = MongoClient(ENV["MONGO_URL"].strip('"'))[ENV["DB_NAME"].strip('"')]
S = {}
CLEAN = []  # (rid, coll, id) deleted via API, in insertion-reverse order
RAW = {"kitchen_tickets": set(), "stock_transfers": set(), "inv_ids": set()}


def adm(rid):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {get_token(ADMIN_EMAIL)[1]}", "X-Restaurant": rid})
    return s


def staff():
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {get_token(MEMBER_EMAIL)[1]}", "X-Restaurant": FL})
    return s


def track(rid, coll, i):
    CLEAN.insert(0, (rid, coll, i))


def prod_sales(rid, pid):
    return [x for x in adm(rid).get(f"{BASE}/sales").json() if x.get("product_id") == pid]


def inv_qty(rid, iid):
    return {i["id"]: i for i in adm(rid).get(f"{BASE}/inventory").json()}[iid]["quantity"]


def view_row(rid, tid, sess=None):
    return next(x for x in (sess or adm(rid)).get(f"{BASE}/tables-view").json()["tables"] if x["id"] == tid)


@pytest.fixture(scope="module", autouse=True)
def setup_and_restore():
    uid = get_token(MEMBER_EMAIL)[0]
    me = next(u for u in adm(FL).get(f"{BASE}/users").json()["users"] if u["user_id"] == uid)
    S["uid"], S["orig"] = uid, me
    yield
    # sales / tips / tables / products / inventory via API
    for rid, coll, i in CLEAN:
        print("cleanup", coll, i, adm(rid).delete(f"{BASE}/{coll}/{i}").status_code)
    MDB.kitchen_tickets.delete_many({"id": {"$in": list(RAW["kitchen_tickets"])}})
    if S.get("table"):
        MDB.kitchen_tickets.delete_many({"table_id": S["table"]})
        MDB.table_orders.delete_many({"table_id": S["table"]})
    MDB.stock_transfers.delete_many({"id": {"$in": list(RAW["stock_transfers"])}})
    MDB.stock_movements.delete_many({"inventory_id": {"$in": list(RAW["inv_ids"])}})
    MDB.inventory.delete_many({"id": {"$in": list(RAW["inv_ids"])}, "name": {"$regex": "^TEST_"}})
    o = S["orig"]
    print("restore role", adm(FL).patch(f"{BASE}/users/{uid}/role", json={"role": o.get("role") or "member"}).status_code)
    print("restore assign", adm(FL).patch(f"{BASE}/users/{uid}/assignment",
                                          json={"restaurant_id": o.get("restaurant_id") or FL, "staff_id": o.get("staff_id") or ""}).status_code)


# --- setup in Etiler ---
def test_setup():
    s = adm(ET)
    inv = s.post(f"{BASE}/inventory", json={"name": "TEST_it19_çiğ", "quantity": 20, "unit": "kg", "minimum": 1, "unit_cost": 40})
    assert inv.status_code == 200, inv.text
    S["inv"] = inv.json()["id"]; RAW["inv_ids"].add(S["inv"])
    p = s.post(f"{BASE}/products", json={"name": "TEST_It19_Kebap", "category": "TEST", "price": 100, "recipe": [{"inventory_id": S["inv"], "amount": 0.5}]})
    assert p.status_code == 200, p.text
    S["kebap"] = p.json()["id"]; track(ET, "products", S["kebap"])
    p2 = s.post(f"{BASE}/products", json={"name": "TEST_It19_Ayran", "category": "TEST", "price": 30})
    S["ayran"] = p2.json()["id"]; track(ET, "products", S["ayran"])
    t = s.post(f"{BASE}/tables", json={"name": "TEST_It19_M1", "seats": 4})
    assert t.status_code == 200, t.text
    S["table"] = t.json()["id"]; track(ET, "tables", S["table"])
    S["rec0"] = s.get(f"{BASE}/cash/reconciliation").json()["payments"]


# --- kitchen tickets ---
def kitchen_for_table(rid, sess=None):
    return [k for k in (sess or adm(rid)).get(f"{BASE}/kitchen").json() if k["table_id"] == S["table"]]


def test_kitchen_ticket_create_merge_reduce():
    s, T = adm(ET), S["table"]
    assert s.post(f"{BASE}/tables/{T}/items", json={"product_id": S["kebap"], "quantity": 2}).status_code == 200
    assert s.post(f"{BASE}/tables/{T}/items", json={"product_id": S["ayran"], "quantity": 1}).status_code == 200
    ks = kitchen_for_table(ET)
    assert len(ks) == 1 and ks[0]["status"] == "Yeni"
    RAW["kitchen_tickets"].add(ks[0]["id"]); S["k1"] = ks[0]["id"]
    q = {i["product_id"]: i["quantity"] for i in ks[0]["items"]}
    assert q == {S["kebap"]: 2, S["ayran"]: 1}
    assert s.post(f"{BASE}/tables/{T}/items", json={"product_id": S["kebap"], "quantity": -1}).status_code == 200
    q = {i["product_id"]: i["quantity"] for i in kitchen_for_table(ET)[0]["items"]}
    assert q[S["kebap"]] == 1
    # negative beyond order -> 422
    r = s.post(f"{BASE}/tables/{T}/items", json={"product_id": S["ayran"], "quantity": -5})
    assert r.status_code == 422, r.text
    # scoped per restaurant
    assert kitchen_for_table(FL) == []


def test_kitchen_ticket_delete_at_zero_and_new_after_status():
    s, T = adm(ET), S["table"]
    # temp product to show line removal; whole ticket deletion tested on a separate table
    t2 = s.post(f"{BASE}/tables", json={"name": "TEST_It19_M2", "seats": 2}).json()["id"]; track(ET, "tables", t2)
    assert s.post(f"{BASE}/tables/{t2}/items", json={"product_id": S["ayran"], "quantity": 1}).status_code == 200
    assert any(k["table_id"] == t2 for k in s.get(f"{BASE}/kitchen").json())
    assert s.post(f"{BASE}/tables/{t2}/items", json={"product_id": S["ayran"], "quantity": -1}).status_code == 200
    assert not any(k["table_id"] == t2 for k in s.get(f"{BASE}/kitchen").json()), "ticket should be deleted at 0"
    MDB.table_orders.delete_many({"table_id": t2})
    # status flow
    assert s.post(f"{BASE}/kitchen/{S['k1']}/status", json={"status": "Bogus"}).status_code == 422
    assert adm(FL).post(f"{BASE}/kitchen/{S['k1']}/status", json={"status": "Hazır"}).status_code == 404
    assert s.post(f"{BASE}/kitchen/{S['k1']}/status", json={"status": "Hazırlanıyor"}).status_code == 200
    assert s.post(f"{BASE}/tables/{T}/items", json={"product_id": S["kebap"], "quantity": 1}).status_code == 200
    ks = kitchen_for_table(ET)
    assert len(ks) == 2 and {k["status"] for k in ks} == {"Hazırlanıyor", "Yeni"}
    for k in ks:
        RAW["kitchen_tickets"].add(k["id"])
    S["k2"] = next(k["id"] for k in ks if k["status"] == "Yeni")
    assert s.post(f"{BASE}/kitchen/{S['k1']}/status", json={"status": "Hazır"}).status_code == 200
    assert view_row(ET, T)["ready_count"] == 1
    assert s.post(f"{BASE}/kitchen/{S['k1']}/status", json={"status": "Teslim edildi"}).status_code == 200
    assert view_row(ET, T)["ready_count"] == 0
    assert all(k["id"] != S["k1"] for k in s.get(f"{BASE}/kitchen").json())
    # order now: kebap 2, ayran 1 = 230


# --- split bill ---
def test_amount_mode_pending_and_validation():
    s, T = adm(ET), S["table"]
    r = s.post(f"{BASE}/tables/{T}/pay", json={"payment": "Nakit", "amount": 500})
    assert r.status_code == 422 and "En fazla 230" in r.text, r.text
    r = s.post(f"{BASE}/tables/{T}/pay", json={"payment": "Nakit", "amount": 100, "tip": 10})
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "closed": False, "remaining": 130}
    assert prod_sales(ET, S["kebap"]) == [] and prod_sales(ET, S["ayran"]) == []
    order = view_row(ET, T)["order"]
    assert len(order["pending"]) == 1 and order["pending"][0]["amount"] == 100
    pid = order["pending"][0]["id"]
    tips = [x for x in s.get(f"{BASE}/tips").json() if "TEST_It19_M1" in x.get("note", "")]
    assert len(tips) == 1 and tips[0]["amount"] == 10
    # cancel blocked
    assert s.post(f"{BASE}/tables/{T}/cancel").status_code == 409
    # remove pending -> tip removed
    assert s.post(f"{BASE}/tables/{T}/pending/{pid}/remove").status_code == 200
    assert [x for x in s.get(f"{BASE}/tips").json() if "TEST_It19_M1" in x.get("note", "")] == []
    assert s.post(f"{BASE}/tables/{T}/pending/{pid}/remove").status_code == 404
    r = s.post(f"{BASE}/tables/{T}/pay", json={"payment": "Nakit", "amount": 100, "tip": 10})
    assert r.status_code == 200 and r.json()["remaining"] == 130


def test_items_mode_and_validation():
    s, T = adm(ET), S["table"]
    assert s.post(f"{BASE}/tables/{T}/pay", json={"payment": "Kart", "items": [{"product_id": S["kebap"], "quantity": 5}]}).status_code == 422
    # paying both kebaps (200) would leave 30 < pending 100 -> 422
    assert s.post(f"{BASE}/tables/{T}/pay", json={"payment": "Kart", "items": [{"product_id": S["kebap"], "quantity": 2}]}).status_code == 422
    r = s.post(f"{BASE}/tables/{T}/pay", json={"payment": "Kart", "items": [{"product_id": S["ayran"], "quantity": 1}]})
    assert r.status_code == 200, r.text
    assert r.json()["closed"] is False and r.json()["remaining"] == 100
    sales = prod_sales(ET, S["ayran"])
    assert len(sales) == 1 and sales[0]["payment"] == "Kart" and sales[0]["amount"] == 30
    for x in sales:
        track(ET, "sales", x["id"])
    order = view_row(ET, T)["order"]
    assert [i["product_id"] for i in order["items"]] == [S["kebap"]] and order["total"] == 200
    # adding negative so total < pending -> 422
    assert s.post(f"{BASE}/tables/{T}/items", json={"product_id": S["kebap"], "quantity": -2}).status_code == 422


def test_final_amount_closes_with_proportional_sales_and_stock():
    s, T = adm(ET), S["table"]
    before = inv_qty(ET, S["inv"])
    r = s.post(f"{BASE}/tables/{T}/pay", json={"payment": "Yemek kartı"})  # pay the rest (100)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "closed": True, "remaining": 0}
    sales = prod_sales(ET, S["kebap"])
    for x in sales:
        track(ET, "sales", x["id"])
    by = {x["payment"]: x for x in sales}
    assert set(by) == {"Nakit", "Yemek kartı"}, sales
    assert by["Nakit"]["amount"] == 100 and by["Yemek kartı"]["amount"] == 100
    assert by["Nakit"]["quantity"] == pytest.approx(1) and by["Yemek kartı"]["quantity"] == pytest.approx(1)
    assert inv_qty(ET, S["inv"]) == pytest.approx(before - 1.0)
    assert view_row(ET, T)["order"] is None
    pay = s.get(f"{BASE}/cash/reconciliation").json()["payments"]
    d = {k: round(pay[k] - S["rec0"].get(k, 0), 2) for k in pay}
    assert d == {"Nakit": 100, "Kart": 30, "Yemek kartı": 100}, d
    assert s.post(f"{BASE}/tables/{T}/pay", json={"payment": "Nakit"}).status_code == 422
    for t in [x for x in s.get(f"{BASE}/tips").json() if "TEST_It19_M1" in x.get("note", "")]:
        track(ET, "tips", t["id"])


def test_uneven_split_fractional():
    s, T = adm(ET), S["table"]
    assert s.post(f"{BASE}/tables/{T}/items", json={"product_id": S["kebap"], "quantity": 1}).status_code == 200
    assert s.post(f"{BASE}/tables/{T}/pay", json={"payment": "Nakit", "amount": 33.33}).status_code == 200
    r = s.post(f"{BASE}/tables/{T}/pay", json={"payment": "Kart", "amount": 66.67})
    assert r.status_code == 200 and r.json()["closed"] is True, r.text
    new = [x for x in prod_sales(ET, S["kebap"]) if (ET, "sales", x["id"]) not in CLEAN]
    for x in new:
        track(ET, "sales", x["id"])
    assert len(new) == 2
    assert round(sum(x["amount"] for x in new), 2) == 100
    assert sum(x["quantity"] for x in new) == pytest.approx(1, abs=1e-3)


def test_close_endpoint_pays_rest():
    s, T = adm(ET), S["table"]
    assert s.post(f"{BASE}/tables/{T}/items", json={"product_id": S["ayran"], "quantity": 2}).status_code == 200
    r = s.post(f"{BASE}/tables/{T}/close", json={"payment": "Kart", "tip": 0})
    assert r.status_code == 200 and r.json()["closed"] is True, r.text
    new = [x for x in prod_sales(ET, S["ayran"]) if (ET, "sales", x["id"]) not in CLEAN]
    for x in new:
        track(ET, "sales", x["id"])
    assert len(new) == 1 and new[0]["amount"] == 60 and new[0]["payment"] == "Kart"
    # cancel with no payment still works
    assert s.post(f"{BASE}/tables/{T}/items", json={"product_id": S["ayran"], "quantity": 1}).status_code == 200
    assert s.post(f"{BASE}/tables/{T}/cancel").status_code == 200
    assert not any(k["status"] == "Yeni" for k in kitchen_for_table(ET))


# --- staff role ---
def test_staff_kitchen_and_pay():
    a = adm(FL)
    assert a.patch(f"{BASE}/users/{S['uid']}/role", json={"role": "staff"}).status_code == 200
    assert a.patch(f"{BASE}/users/{S['uid']}/assignment", json={"restaurant_id": ET, "staff_id": ""}).status_code == 200
    st, T = staff(), S["table"]
    assert st.post(f"{BASE}/tables/{T}/items", json={"product_id": S["ayran"], "quantity": 2}).status_code == 200
    ks = kitchen_for_table(ET, st)
    assert ks and ks[-1]["status"] == "Yeni"
    RAW["kitchen_tickets"].update(k["id"] for k in ks)
    assert st.post(f"{BASE}/kitchen/{ks[-1]['id']}/status", json={"status": "Hazır"}).status_code == 200
    assert view_row(ET, T, st)["ready_count"] >= 1
    r = st.post(f"{BASE}/tables/{T}/pay", json={"payment": "Nakit", "amount": 20, "tip": 5})
    assert r.status_code == 200, r.text
    pid = view_row(ET, T, st)["order"]["pending"][0]["id"]
    assert st.post(f"{BASE}/tables/{T}/pending/{pid}/remove").status_code == 200
    r = st.post(f"{BASE}/tables/{T}/pay", json={"payment": "Nakit", "items": [{"product_id": S["ayran"], "quantity": 2}]})
    assert r.status_code == 200 and r.json()["closed"] is True, r.text
    new = [x for x in prod_sales(ET, S["ayran"]) if (ET, "sales", x["id"]) not in CLEAN]
    for x in new:
        track(ET, "sales", x["id"])
    assert len(new) == 1 and new[0]["created_by"] == MEMBER_EMAIL
    assert st.post(f"{BASE}/stock-transfers", json={"to_restaurant": DU, "items": [{"inventory_id": S["inv"], "quantity": 1}]}).status_code == 403
    assert st.get(f"{BASE}/stock-transfers").status_code == 403
    for k in kitchen_for_table(ET, st):
        st.post(f"{BASE}/kitchen/{k['id']}/status", json={"status": "Teslim edildi"})


# --- stock transfers ---
def test_transfer_validation():
    s = adm(ET)
    body = {"to_restaurant": ET, "items": [{"inventory_id": S["inv"], "quantity": 1}]}
    assert s.post(f"{BASE}/stock-transfers", json=body).status_code == 422
    assert adm("all").post(f"{BASE}/stock-transfers", json={**body, "to_restaurant": DU}).status_code == 400
    assert s.post(f"{BASE}/stock-transfers", json={**body, "to_restaurant": "nope"}).status_code == 422
    r = s.post(f"{BASE}/stock-transfers", json={"to_restaurant": DU, "items": [{"inventory_id": S["inv"], "quantity": 9999}]})
    assert r.status_code == 422 and "stokta" in r.text, r.text
    assert s.post(f"{BASE}/stock-transfers", json={"to_restaurant": DU, "items": []}).status_code == 422


def test_transfer_creates_target_item_and_movements():
    s = adm(ET)
    src_before = inv_qty(ET, S["inv"])
    r = s.post(f"{BASE}/stock-transfers", json={"to_restaurant": DU, "items": [{"inventory_id": S["inv"], "quantity": 3}], "note": "TEST_note"})
    assert r.status_code == 200, r.text
    doc = r.json(); RAW["stock_transfers"].add(doc["id"])
    S["tr1"] = doc
    to_id = doc["items"][0]["to_id"]; RAW["inv_ids"].add(to_id); S["du_inv"] = to_id
    assert doc["from_restaurant"] == ET and doc["to_restaurant"] == DU and doc["value"] == 120
    assert inv_qty(ET, S["inv"]) == pytest.approx(src_before - 3)
    du = {i["id"]: i for i in adm(DU).get(f"{BASE}/inventory").json()}[to_id]
    assert du["name"] == "TEST_it19_çiğ" and du["unit"] == "kg" and du["unit_cost"] == 40 and du["quantity"] == 3
    mv_src = adm(ET).get(f"{BASE}/stock-movements", params={"inventory_id": S["inv"]}).json()
    mv_dst = adm(DU).get(f"{BASE}/stock-movements", params={"inventory_id": to_id}).json()
    assert any(m["reason"].startswith("Transfer →") and m["delta"] == -3 for m in mv_src), mv_src[:3]
    assert any(m["reason"].startswith("Transfer ←") and m["delta"] == 3 for m in mv_dst), mv_dst[:3]
    # lists
    out = [t for t in adm(ET).get(f"{BASE}/stock-transfers").json() if t["id"] == doc["id"]]
    inc = [t for t in adm(DU).get(f"{BASE}/stock-transfers").json() if t["id"] == doc["id"]]
    assert out and inc
    assert not [t for t in adm(FL).get(f"{BASE}/stock-transfers").json() if t["id"] == doc["id"]]


def test_transfer_merges_turkish_case_insensitive():
    du = adm(DU)
    # DU already has TEST_it19_çiğ (from previous transfer); create an upper-case variant scenario in ET
    e = adm(ET).post(f"{BASE}/inventory", json={"name": "TEST_İT19_ÇİĞ", "quantity": 5, "unit": "kg", "unit_cost": 40})
    assert e.status_code == 200
    eid = e.json()["id"]; RAW["inv_ids"].add(eid)
    r = adm(ET).post(f"{BASE}/stock-transfers", json={"to_restaurant": DU, "items": [{"inventory_id": eid, "quantity": 2}]})
    assert r.status_code == 200, r.text
    RAW["stock_transfers"].add(r.json()["id"]); S["tr2"] = r.json()
    assert r.json()["items"][0]["to_id"] == S["du_inv"], "should merge into existing same-name (Turkish case-insensitive) item"
    assert {i["id"]: i for i in du.get(f"{BASE}/inventory").json()}[S["du_inv"]]["quantity"] == 5


def test_transfer_undo_rules():
    # only source can undo
    assert adm(DU).delete(f"{BASE}/stock-transfers/{S['tr1']['id']}").status_code == 404
    assert adm("all").delete(f"{BASE}/stock-transfers/{S['tr1']['id']}").status_code == 400
    src_before = inv_qty(ET, S["inv"])
    r = adm(ET).delete(f"{BASE}/stock-transfers/{S['tr1']['id']}")
    assert r.status_code == 200, r.text
    assert inv_qty(ET, S["inv"]) == pytest.approx(src_before + 3)
    assert inv_qty(DU, S["du_inv"]) == pytest.approx(2)
    assert not [t for t in adm(ET).get(f"{BASE}/stock-transfers").json() if t["id"] == S["tr1"]["id"]]
    # 409 when target consumed
    assert adm(DU).post(f"{BASE}/inventory/{S['du_inv']}/count", json={"quantity": 1}).status_code == 200
    r = adm(ET).delete(f"{BASE}/stock-transfers/{S['tr2']['id']}")
    assert r.status_code == 409, r.text
    assert inv_qty(DU, S["du_inv"]) == pytest.approx(1)


# --- reports ---
def test_export_all_has_restaurant_section():
    from openpyxl import load_workbook
    from pypdf import PdfReader
    r = adm("all").get(f"{BASE}/reports/export", params={"period": "daily", "format": "xlsx"})
    assert r.status_code == 200
    cells = [str(c.value) for row in load_workbook(io.BytesIO(r.content)).active.iter_rows() for c in row if c.value is not None]
    assert "Restoran Bazlı Özet" in cells and "TOPLAM" in cells
    for n in ("Florya Taşfırın", "Etiler Marmaris", "Dürümtır"):
        assert n in cells
    p = adm("all").get(f"{BASE}/reports/export", params={"period": "daily", "format": "pdf"})
    assert p.status_code == 200 and p.content[:4] == b"%PDF"
    text = "".join(pg.extract_text() or "" for pg in PdfReader(io.BytesIO(p.content)).pages)
    assert "Restoran" in text and "TOPLAM" in text
    one = adm(ET).get(f"{BASE}/reports/export", params={"period": "daily", "format": "xlsx"})
    cells1 = [str(c.value) for row in load_workbook(io.BytesIO(one.content)).active.iter_rows() for c in row if c.value is not None]
    assert "Restoran Bazlı Özet" not in cells1


def test_full_report_and_email_body():
    sys.path.insert(0, "/app/backend")
    import server
    import mailer
    from scope import current_rid
    from motor.motor_asyncio import AsyncIOMotorClient

    async def run():
        raw = AsyncIOMotorClient(ENV["MONGO_URL"].strip('"'))[ENV["DB_NAME"].strip('"')]
        server.db = server.ScopedDB(raw) if hasattr(server, "ScopedDB") else server.db
        tok = current_rid.set(None)
        try:
            rep = await server.full_report("daily")
        finally:
            current_rid.reset(tok)
        recs = []
        for rid in (FL, ET, DU):
            t = current_rid.set(rid)
            try:
                recs.append(await server.cash_reconciliation(None))
            finally:
                current_rid.reset(t)
        return rep, recs
    rep, recs = asyncio.run(run())
    assert [r["id"] for r in rep["restaurants"]] == [FL, ET, DU]
    for k in server.REC_KEYS:
        assert rep["reconciliation"][k] == pytest.approx(round(sum(x[k] for x in recs), 2)), k
    assert rep["revenue"] == pytest.approx(sum(r["revenue"] for r in rep["restaurants"]))
    sent = {}
    orig = mailer._send
    mailer._send = lambda subject, body, *a, **k: sent.update(subject=subject, body=body)
    try:
        rep["low_stock"] = []
        mailer.send_report_email(b"%PDF", rep, "2026-01-01")
    finally:
        mailer._send = orig
    for n in ("FLORYA TAŞFIRIN", "ETILER MARMARIS", "DÜRÜMTIR"):
        assert n in sent["body"].upper() or n.replace("I", "İ") in sent["body"], n
    assert "TÜM RESTORANLAR" in sent["body"]
    print(sent["body"][:1500])
