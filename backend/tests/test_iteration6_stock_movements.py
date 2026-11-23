# Iteration 6: stock movement history, low-stock in mailer/PDF (python-level, no real email)
import os
import sys
import uuid
import pytest
import requests
from dotenv import dotenv_values

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or dotenv_values("/app/frontend/.env")["REACT_APP_BACKEND_URL"]).rstrip("/")
SUFFIX = uuid.uuid4().hex[:6]
CREATED = []


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    yield sess
    for coll, _id in reversed(CREATED):
        sess.delete(f"{BASE_URL}/api/{coll}/{_id}")


def create(s, coll, payload):
    r = s.post(f"{BASE_URL}/api/{coll}", json=payload)
    assert r.status_code == 200, r.text
    d = r.json()
    CREATED.append((coll, d["id"]))
    return d


def moves(s, inv_id=None):
    r = s.get(f"{BASE_URL}/api/stock-movements", params={"inventory_id": inv_id} if inv_id else {})
    assert r.status_code == 200
    return r.json()


@pytest.fixture(scope="module")
def setup(s):
    a = create(s, "inventory", {"name": f"TEST_Kofte_{SUFFIX}", "quantity": 10, "unit": "kg", "minimum": 2})
    b = create(s, "inventory", {"name": f"TEST_Ekmek_{SUFFIX}", "quantity": 50, "unit": "adet", "minimum": 5})
    p = create(s, "products", {"name": f"TEST_Burger_{SUFFIX}", "price": 100, "cost": 40,
                               "recipe": [{"inventory_id": a["id"], "amount": 0.2}, {"inventory_id": b["id"], "amount": 1}]})
    return a, b, p


# Initial record
def test_initial_record(s, setup):
    a, b, _ = setup
    m = moves(s, a["id"])
    assert len(m) == 1 and m[0]["reason"] == "İlk kayıt"
    assert m[0]["delta"] == 10 and m[0]["quantity_after"] == 10 and m[0]["unit"] == "kg"
    assert m[0]["inventory_name"] == a["name"] and m[0]["product_name"] == "" and "_id" not in m[0]
    assert all(x["inventory_id"] == a["id"] for x in m)


# Sale -> negative deltas, edit -> reversal+new, delete -> stock return
def test_sale_edit_delete_flow(s, setup):
    a, b, p = setup
    sale = create(s, "sales", {"product_id": p["id"], "product_name": p["name"], "quantity": 2, "unit_price": 100, "unit_cost": 40, "amount": 200})
    ma = moves(s, a["id"])
    assert ma[0]["reason"] == "Satış" and ma[0]["delta"] == -0.4 and ma[0]["quantity_after"] == 9.6
    assert ma[0]["product_name"] == p["name"] and ma[0]["sale_quantity"] == 2
    mb = moves(s, b["id"])
    assert mb[0]["delta"] == -2 and mb[0]["quantity_after"] == 48
    # newest first
    assert ma[0]["created_at"] >= ma[-1]["created_at"]

    r = s.put(f"{BASE_URL}/api/sales/{sale['id']}", json={**sale, "quantity": 3, "amount": 300})
    assert r.status_code == 200
    ma = moves(s, a["id"])
    reasons = [x["reason"] for x in ma[:2]]
    assert "Satış düzeltildi (eski kayıt geri alındı)" in reasons and "Satış düzeltildi (yeni kayıt)" in reasons
    new = next(x for x in ma[:2] if x["reason"].endswith("(yeni kayıt)"))
    rev = next(x for x in ma[:2] if x["reason"].endswith("geri alındı)"))
    assert rev["delta"] == 0.4 and new["delta"] == -0.6 and new["quantity_after"] == 9.4 and new["sale_quantity"] == 3
    assert ma[0]["reason"].endswith("(yeni kayıt)"), f"newest should be new record, got {reasons}"

    assert s.delete(f"{BASE_URL}/api/sales/{sale['id']}").status_code == 200
    CREATED.remove(("sales", sale["id"]))
    ma = moves(s, a["id"])
    assert ma[0]["reason"] == "Satış silindi (stok iade)" and ma[0]["delta"] == 0.6 and ma[0]["quantity_after"] == 10
    mb = moves(s, b["id"])
    assert mb[0]["reason"] == "Satış silindi (stok iade)" and mb[0]["delta"] == 3 and mb[0]["quantity_after"] == 50


# Manual inventory edits
def test_manual_edit(s, setup):
    a, _, _ = setup
    before = len(moves(s, a["id"]))
    cur = next(i for i in s.get(f"{BASE_URL}/api/inventory").json() if i["id"] == a["id"])
    r = s.put(f"{BASE_URL}/api/inventory/{a['id']}", json={**cur, "quantity": 7.5})
    assert r.status_code == 200
    m = moves(s, a["id"])
    assert len(m) == before + 1 and m[0]["reason"] == "Manuel sayım / düzeltme" and m[0]["delta"] == -2.5 and m[0]["quantity_after"] == 7.5
    r = s.put(f"{BASE_URL}/api/inventory/{a['id']}", json={**cur, "quantity": 7.5, "minimum": 3, "unit": "kg"})
    assert r.status_code == 200
    assert len(moves(s, a["id"])) == before + 1


# Unfiltered list includes both items and is sorted desc
def test_all_movements_sorted(s, setup):
    a, b, _ = setup
    m = moves(s)
    ids = {x["inventory_id"] for x in m}
    assert a["id"] in ids and b["id"] in ids
    ts = [x["created_at"] for x in m]
    assert ts == sorted(ts, reverse=True)
    for f in ["inventory_name", "unit", "delta", "quantity_after", "reason", "product_name", "sale_quantity"]:
        assert f in m[0]


# Mailer/PDF low stock (python-level, no SMTP)
def test_low_stock_text_and_pdf():
    sys.path.insert(0, "/app/backend")
    import mailer
    import exports
    txt = mailer.low_stock_text([{"name": "Domates", "quantity": 1.5, "unit": "kg", "minimum": 3}])
    assert "KRİTİK STOK" in txt and "Domates: 1,5 kg (minimum 3)" in txt
    assert "Tüm malzemeler" in mailer.low_stock_text([])
    rep = {"period": "daily", "start": "2026-01-10T00:00:00+03:00", "end": "2026-01-10T23:59:59+03:00", "revenue": 0, "expenses": 0, "profit": 0,
           "sales_count": 0, "top_products": [], "sales": [], "expenses_list": [],
           "reconciliation": {"date": "2026-01-10", "opening": 0, "sales": 0, "expenses": 0, "expected_closing": 0, "actual_closing": 0, "difference": 0},
           "low_stock": [{"name": "Domates", "quantity": 1.5, "unit": "kg", "minimum": 3}]}
    titles = [t for t, _, _ in exports._sections(rep)]
    assert "Kritik Stok" in titles
    pdf = exports.build_pdf(rep)
    assert pdf[:4] == b"%PDF" and len(pdf) > 1000
    rep2 = {k: v for k, v in rep.items() if k != "low_stock"}
    assert "Kritik Stok" not in [t for t, _, _ in exports._sections(rep2)]
    rep["low_stock"] = []
    assert exports.build_pdf(rep)[:4] == b"%PDF"
