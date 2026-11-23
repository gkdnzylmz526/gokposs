# Iteration 5: CRUD update/delete, stock deduction, custom-range reports, cron + email endpoints
import os
import time
import uuid
import pytest
import requests
from dotenv import dotenv_values

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL") or dotenv_values("/app/frontend/.env")["REACT_APP_BACKEND_URL"]
BASE_URL = BASE_URL.rstrip("/")
SECRET = dotenv_values("/app/backend/.env")["WEBHOOK_CRON_SECRET"]
CREATED = []  # (collection, id)
RUN_IDS = []
SUFFIX = uuid.uuid4().hex[:6]


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    yield sess
    for coll, _id in CREATED:
        sess.delete(f"{BASE_URL}/api/{coll}/{_id}")
    with open("/tmp/iter5_run_ids.txt", "a") as f:
        f.write("\n".join(RUN_IDS) + "\n")


def create(s, coll, payload):
    r = s.post(f"{BASE_URL}/api/{coll}", json=payload)
    assert r.status_code == 200, r.text
    d = r.json()
    CREATED.append((coll, d["id"]))
    return d


def inv_qty(s, inv_id):
    items = s.get(f"{BASE_URL}/api/inventory").json()
    return next(i for i in items if i["id"] == inv_id)["quantity"]


# CRUD update/delete
@pytest.mark.parametrize("coll,payload,patch", [
    ("expenses", {"amount": 100, "category": "TEST_cat", "note": "a"}, {"amount": 250, "category": "TEST_cat2", "note": "b"}),
    ("staff", {"name": f"TEST_staff_{SUFFIX}"}, {"name": f"TEST_staff2_{SUFFIX}", "status": "Aktif"}),
    ("cash", {"opening": 100, "closing": 200}, {"opening": 150, "closing": 300, "note": "TEST"}),
    ("inventory", {"name": f"TEST_inv_{SUFFIX}", "quantity": 3}, {"name": f"TEST_inv_{SUFFIX}", "quantity": 7, "unit": "kg"}),
    ("products", {"name": f"TEST_prod_{SUFFIX}", "price": 10}, {"name": f"TEST_prod2_{SUFFIX}", "price": 20, "cost": 5}),
])
def test_update_and_delete(s, coll, payload, patch):
    d = create(s, coll, payload)
    r = s.put(f"{BASE_URL}/api/{coll}/{d['id']}", json={**patch, "id": "hacked", "created_at": "2000-01-01T00:00:00+00:00"})
    assert r.status_code == 200, r.text
    u = r.json()
    assert u["id"] == d["id"] and u["created_at"] == d["created_at"]
    for k, v in patch.items():
        assert u[k] == v
    got = next(i for i in s.get(f"{BASE_URL}/api/{coll}").json() if i["id"] == d["id"])
    for k, v in patch.items():
        assert got[k] == v
    assert s.delete(f"{BASE_URL}/api/{coll}/{d['id']}").status_code == 200
    assert not any(i["id"] == d["id"] for i in s.get(f"{BASE_URL}/api/{coll}").json())
    assert s.delete(f"{BASE_URL}/api/{coll}/{d['id']}").status_code == 404


def test_update_unknown_404(s):
    r = s.put(f"{BASE_URL}/api/expenses/nonexistent-{SUFFIX}", json={"amount": 1})
    assert r.status_code == 404
    assert r.json()["detail"] == "Kayıt bulunamadı"


# Stock deduction via recipe
def test_recipe_stock_flow(s):
    inv = create(s, "inventory", {"name": f"TEST_Dana kıyma {SUFFIX}", "quantity": 10, "unit": "kg"})
    prod = create(s, "products", {"name": f"TEST_Köfte {SUFFIX}", "price": 200, "cost": 80, "recipe": [{"inventory_id": inv["id"], "amount": 0.15}]})
    sale = create(s, "sales", {"product_id": prod["id"], "product_name": prod["name"], "quantity": 4, "unit_price": 200, "amount": 800})
    assert inv_qty(s, inv["id"]) == pytest.approx(9.4)
    r = s.put(f"{BASE_URL}/api/sales/{sale['id']}", json={"product_id": prod["id"], "product_name": prod["name"], "quantity": 2, "unit_price": 200, "amount": 400})
    assert r.status_code == 200
    assert inv_qty(s, inv["id"]) == pytest.approx(9.7)
    assert s.delete(f"{BASE_URL}/api/sales/{sale['id']}").status_code == 200
    assert inv_qty(s, inv["id"]) == pytest.approx(10)


# Name-match deduction (no recipe), case-insensitive
def test_name_match_stock(s):
    name = f"TEST_Kola{SUFFIX}"
    inv = create(s, "inventory", {"name": name, "quantity": 20})
    prod = create(s, "products", {"name": name, "price": 30})
    sale = create(s, "sales", {"product_id": prod["id"], "product_name": name.lower(), "quantity": 3, "amount": 90})
    assert inv_qty(s, inv["id"]) == pytest.approx(17)
    s.delete(f"{BASE_URL}/api/sales/{sale['id']}")
    assert inv_qty(s, inv["id"]) == pytest.approx(20)


# Custom range reports (Istanbul-local inclusive)
def test_custom_range(s):
    # 2020-01-01T21:30Z == 2020-01-02 00:30 Istanbul
    a = create(s, "sales", {"product_name": f"TEST_r_{SUFFIX}", "quantity": 1, "amount": 111, "created_at": "2020-01-01T21:30:00+00:00"})
    b = create(s, "sales", {"product_name": f"TEST_r_{SUFFIX}", "quantity": 1, "amount": 222, "created_at": "2020-01-03T20:59:00+00:00"})  # 01-03 23:59 IST
    c = create(s, "sales", {"product_name": f"TEST_r_{SUFFIX}", "quantity": 1, "amount": 444, "created_at": "2020-01-03T21:00:00+00:00"})  # 01-04 00:00 IST
    create(s, "expenses", {"amount": 50, "category": "TEST", "created_at": "2020-01-02T10:00:00+00:00"})
    r = s.get(f"{BASE_URL}/api/reports", params={"period": "custom", "start": "2020-01-02", "end": "2020-01-03"})
    assert r.status_code == 200, r.text
    d = r.json()
    ids = {x["id"] for x in d["sales"]}
    assert ids == {a["id"], b["id"]}
    assert d["revenue"] == 333 and d["expenses"] == 50 and d["profit"] == 283
    r1 = s.get(f"{BASE_URL}/api/reports", params={"period": "custom", "start": "2020-01-01", "end": "2020-01-01"}).json()
    assert r1["sales_count"] == 0
    r4 = s.get(f"{BASE_URL}/api/reports", params={"period": "custom", "start": "2020-01-04", "end": "2020-01-04"}).json()
    assert {x["id"] for x in r4["sales"]} == {c["id"]}


@pytest.mark.parametrize("params", [
    {"period": "custom"}, {"period": "custom", "start": "2020-01-02"}, {"period": "custom", "start": "bad", "end": "2020-01-02"},
    {"period": "custom", "start": "2020-01-05", "end": "2020-01-02"}, {"period": "yearly"},
])
def test_custom_range_invalid(s, params):
    assert s.get(f"{BASE_URL}/api/reports", params=params).status_code == 422


@pytest.mark.parametrize("fmt,ctype,magic", [("xlsx", "spreadsheetml", b"PK"), ("pdf", "application/pdf", b"%PDF")])
def test_custom_export(s, fmt, ctype, magic):
    r = s.get(f"{BASE_URL}/api/reports/export", params={"period": "custom", "start": "2020-01-02", "end": "2020-01-03", "format": fmt})
    assert r.status_code == 200, r.text[:300]
    assert ctype in r.headers["content-type"] and r.content[:4].startswith(magic)
    assert "2020-01-02_2020-01-03" in r.headers.get("content-disposition", "")
    assert s.get(f"{BASE_URL}/api/reports/export", params={"period": "custom", "format": fmt}).status_code == 422


# Cron endpoint
def test_cron_auth(s):
    assert s.post(f"{BASE_URL}/api/cron/daily-report", json={}).status_code == 401
    assert s.post(f"{BASE_URL}/api/cron/daily-report", json={}, headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_cron_accept_and_duplicate(s):
    rid = f"TEST_run_{SUFFIX}"
    RUN_IDS.append(rid)
    h = {"Authorization": f"Bearer {SECRET}", "X-Webhook-Id": rid}
    r = s.post(f"{BASE_URL}/api/cron/daily-report", json={}, headers=h)
    assert r.status_code == 200 and r.json() == {"status": "accepted"}
    r2 = s.post(f"{BASE_URL}/api/cron/daily-report", json={}, headers=h)
    assert r2.json() == {"status": "duplicate"}
    time.sleep(8)
    st = s.get(f"{BASE_URL}/api/email/status").json()
    rec = [x for x in st["history"] if x.get("key") == rid]
    assert rec and rec[0]["status"] == "failed" and rec[0]["trigger"] == "cron"


def test_cron_empty_body(s):
    rid = f"TEST_run_empty_{SUFFIX}"
    RUN_IDS.append(rid)
    r = s.post(f"{BASE_URL}/api/cron/daily-report", headers={"Authorization": f"Bearer {SECRET}", "X-Webhook-Id": rid})
    assert r.status_code == 200, f"empty-body cron returned {r.status_code} {r.text}"


# Email endpoints
def test_email_status_and_send_now(s):
    st = s.get(f"{BASE_URL}/api/email/status").json()
    assert st["configured"] is False and st["recipient"] == "gkdnzylmz5261@gmail.com"
    r = s.post(f"{BASE_URL}/api/email/send-now")
    assert r.status_code == 502
    assert "E-posta gönderilemedi" in r.json()["detail"]
    hist = s.get(f"{BASE_URL}/api/email/status").json()["history"]
    assert hist[0]["trigger"] == "manual" and hist[0]["status"] == "failed"
