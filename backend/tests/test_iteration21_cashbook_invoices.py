# Iteration 21: manual cash book (incomes, expense payment, purchase invoices + files), settings, wizard-recipe for existing products, report export.
# Ordered shared state; run with -n 0. Cleans everything it created by id.
import io
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import requests
from openpyxl import load_workbook
from pymongo import MongoClient

from conftest import get_token, ADMIN_EMAIL

BASE = open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split()[0].rstrip("/") + "/api"
FL, ET, DU = "florya-tasfirin", "etiler-marmaris", "durumtir"
ENV = dict(l.strip().split("=", 1) for l in open("/app/backend/.env") if "=" in l)
MDB = MongoClient(ENV["MONGO_URL"].strip('"'))[ENV["DB_NAME"].strip('"')]
TODAY = datetime.now(ZoneInfo("Europe/Istanbul")).date()
T = TODAY.isoformat()
S = {"incomes": set(), "invoices": set(), "expenses": set(), "products": set(), "inv": set(), "files": set()}


def adm(rid=FL):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {get_token(ADMIN_EMAIL)[1]}", "X-Restaurant": rid})
    return s


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    orig = adm().get(f"{BASE}/settings").json()
    yield
    s = adm(FL)
    for i in S["invoices"]:
        s.delete(f"{BASE}/invoices/{i}")
    for i in S["incomes"]:
        s.delete(f"{BASE}/incomes/{i}")
    for i in S["expenses"]:
        s.delete(f"{BASE}/expenses/{i}")
    for p in S["products"]:
        s.delete(f"{BASE}/products/{p}")
    MDB.inventory.delete_many({"id": {"$in": list(S["inv"])}, "name": {"$regex": "^TEST_", "$options": "i"}})
    adm("all").put(f"{BASE}/settings", json={"product_sales": False})
    print("orig settings", orig)


def recon(rid=FL, day=T):
    return adm(rid).get(f"{BASE}/cash/reconciliation", params={"date": day}).json()


# ---------- Incomes ----------
def test_income_crud_and_totals():
    rep0 = adm().get(f"{BASE}/reports", params={"period": "daily"}).json()
    rec0 = recon()
    dash0 = adm().get(f"{BASE}/dashboard").json()
    r = adm().post(f"{BASE}/incomes", json={"date": T, "amount": 1234.5, "payment": "Nakit", "category": "TEST_POS", "note": "TEST_inc"})
    assert r.status_code == 200, r.text
    inc = r.json(); S["incomes"].add(inc["id"])
    r2 = adm().post(f"{BASE}/incomes", json={"date": T, "amount": 100, "payment": "Kart", "category": "TEST_POS"})
    assert r2.status_code == 200; S["incomes"].add(r2.json()["id"])
    assert any(x["id"] == inc["id"] and x["amount"] == 1234.5 for x in adm().get(f"{BASE}/incomes").json())
    rep = adm().get(f"{BASE}/reports", params={"period": "daily"}).json()
    assert rep["incomes_total"] == pytest.approx(rep0["incomes_total"] + 1334.5)
    assert rep["revenue"] == pytest.approx(rep0["revenue"] + 1334.5)
    assert rep["payments"]["Nakit"] == pytest.approx(rep0["payments"]["Nakit"] + 1234.5)
    assert rep["payments"]["Kart"] == pytest.approx(rep0["payments"]["Kart"] + 100)
    rec = recon()
    assert rec["cash_sales"] == pytest.approx(rec0["cash_sales"] + 1234.5)
    assert rec["expected_closing"] == pytest.approx(rec0["expected_closing"] + 1234.5)
    dash = adm().get(f"{BASE}/dashboard").json()
    assert dash["weekly"][-1]["revenue"] == pytest.approx(dash0["weekly"][-1]["revenue"] + 1334.5)
    assert "settings" in dash and "incomes" in dash and "invoices" in dash
    # other restaurant not affected
    assert all(x["id"] != inc["id"] for x in adm(ET).get(f"{BASE}/incomes").json())
    # update
    u = adm().put(f"{BASE}/incomes/{inc['id']}", json={"date": T, "amount": 200, "payment": "Yemek kartı", "category": "TEST_POS", "note": "x"})
    assert u.status_code == 200 and u.json()["amount"] == 200 and u.json()["payment"] == "Yemek kartı"
    assert recon()["cash_sales"] == pytest.approx(rec0["cash_sales"])


def test_income_backdated_created_at_and_validation():
    y = (TODAY - timedelta(days=3)).isoformat()
    rec0 = recon(day=y)
    r = adm().post(f"{BASE}/incomes", json={"date": y, "amount": 77, "payment": "Nakit", "category": "TEST_POS"})
    assert r.status_code == 200; d = r.json(); S["incomes"].add(d["id"])
    created = datetime.fromisoformat(d["created_at"]).astimezone(ZoneInfo("Europe/Istanbul"))
    assert created.date().isoformat() == y and created.hour == 12
    assert recon(day=y)["cash_sales"] == pytest.approx(rec0["cash_sales"] + 77)
    rep = adm().get(f"{BASE}/reports", params={"period": "custom", "start": y, "end": y}).json()
    assert any(x["id"] == d["id"] for x in rep["incomes_list"])
    for bad in ({"date": T, "amount": 0}, {"date": T, "amount": 5, "payment": "Çek"}, {"date": "bad", "amount": 5}):
        assert adm().post(f"{BASE}/incomes", json=bad).status_code == 422, bad
    assert adm("all").post(f"{BASE}/incomes", json={"date": T, "amount": 5}).status_code in (400, 403, 409, 422)


# ---------- Expense payment ----------
def test_expense_payment_recon_only_cash():
    rec0 = recon()
    a = adm().post(f"{BASE}/expenses", json={"category": "TEST_Gider", "amount": 50, "payment": "Kart", "note": "TEST_k"})
    assert a.status_code == 200, a.text; S["expenses"].add(a.json()["id"]); assert a.json()["payment"] == "Kart"
    b = adm().post(f"{BASE}/expenses", json={"category": "TEST_Gider", "amount": 30, "note": "TEST_n"})
    assert b.status_code == 200; S["expenses"].add(b.json()["id"]); assert b.json()["payment"] == "Nakit"
    rec = recon()
    assert rec["expenses"] == pytest.approx(rec0["expenses"] + 30)
    assert rec["expected_closing"] == pytest.approx(rec0["expected_closing"] - 30)


# ---------- Invoices ----------
def _new_invoice(**kw):
    body = {"supplier": "TEST_Tedarik", "invoice_no": "TEST-001", "date": T, "due_date": (TODAY + timedelta(days=5)).isoformat(),
            "amount": 500, "vat_rate": 20, "category": "Malzeme alımı", "note": "TEST", "status": "Ödendi", "expense_id": "hack", **kw}
    r = adm().post(f"{BASE}/invoices", json=body)
    assert r.status_code == 200, r.text
    S["invoices"].add(r.json()["id"])
    return r.json()


def test_invoice_create_forces_unpaid():
    inv = _new_invoice()
    assert inv["status"] == "Ödenmedi" and inv["expense_id"] == "" and inv["files"] == []
    assert adm().post(f"{BASE}/invoices", json={"date": T, "amount": 5}).status_code == 422
    assert adm().post(f"{BASE}/invoices", json={"supplier": "TEST_x", "date": T, "amount": 5, "due_date": "05/01"}).status_code == 422


def test_invoice_pay_unpay_and_expense_link():
    inv = _new_invoice()
    rec0 = recon()
    r = adm().post(f"{BASE}/invoices/{inv['id']}/pay", json={"payment": "Nakit", "date": T, "record_expense": True})
    assert r.status_code == 200, r.text
    d = r.json(); assert d["status"] == "Ödendi" and d["expense_id"] and d["paid_payment"] == "Nakit"
    exp = next(x for x in adm().get(f"{BASE}/expenses").json() if x["id"] == d["expense_id"])
    assert exp["invoice_id"] == inv["id"] and exp["amount"] == 500 and exp["payment"] == "Nakit"
    assert recon()["expenses"] == pytest.approx(rec0["expenses"] + 500)
    assert adm().post(f"{BASE}/invoices/{inv['id']}/pay", json={}).status_code == 409
    # PUT preserves status & syncs expense amount
    u = adm().put(f"{BASE}/invoices/{inv['id']}", json={**{k: inv[k] for k in ("supplier", "invoice_no", "date", "due_date", "vat_rate", "category", "note")}, "amount": 650, "status": "Ödenmedi", "expense_id": ""})
    assert u.status_code == 200 and u.json()["status"] == "Ödendi" and u.json()["expense_id"] == d["expense_id"]
    exp = next(x for x in adm().get(f"{BASE}/expenses").json() if x["id"] == d["expense_id"])
    assert exp["amount"] == 650
    # unpay deletes expense
    assert adm().post(f"{BASE}/invoices/{inv['id']}/unpay").status_code == 200
    assert all(x["id"] != d["expense_id"] for x in adm().get(f"{BASE}/expenses").json())
    got = next(x for x in adm().get(f"{BASE}/invoices").json() if x["id"] == inv["id"])
    assert got["status"] == "Ödenmedi" and got["expense_id"] == ""


def test_invoice_pay_backdated_without_expense_and_delete_expense_resets():
    inv = _new_invoice(amount=120)
    past = (TODAY - timedelta(days=2)).isoformat()
    r = adm().post(f"{BASE}/invoices/{inv['id']}/pay", json={"payment": "Havale", "date": past, "record_expense": False})
    assert r.status_code == 200 and r.json()["expense_id"] == "" and r.json()["paid_at"] == past
    adm().post(f"{BASE}/invoices/{inv['id']}/unpay")
    r = adm().post(f"{BASE}/invoices/{inv['id']}/pay", json={"payment": "Kart", "date": past})
    eid = r.json()["expense_id"]
    exp = MDB.expenses.find_one({"id": eid})
    assert datetime.fromisoformat(exp["created_at"]).astimezone(ZoneInfo("Europe/Istanbul")).date().isoformat() == past
    assert adm().delete(f"{BASE}/expenses/{eid}").status_code == 200
    got = next(x for x in adm().get(f"{BASE}/invoices").json() if x["id"] == inv["id"])
    assert got["status"] == "Ödenmedi" and got["expense_id"] == ""
    assert adm().post(f"{BASE}/invoices/{inv['id']}/pay", json={"payment": "Yemek kartı"}).status_code == 422


def test_invoice_delete_removes_linked_expense():
    inv = _new_invoice(amount=90)
    eid = adm().post(f"{BASE}/invoices/{inv['id']}/pay", json={"payment": "Havale"}).json()["expense_id"]
    assert adm().delete(f"{BASE}/invoices/{inv['id']}").status_code == 200
    S["invoices"].discard(inv["id"])
    assert MDB.expenses.find_one({"id": eid}) is None
    assert adm().get(f"{BASE}/invoices").json() and all(x["id"] != inv["id"] for x in adm().get(f"{BASE}/invoices").json())
    assert adm().post(f"{BASE}/invoices/{inv['id']}/pay", json={}).status_code == 404


# ---------- Files ----------
PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


def test_invoice_file_upload_download_delete():
    inv = _new_invoice(amount=10)
    r = adm().post(f"{BASE}/invoices/{inv['id']}/files", files={"file": ("TEST_fatura.png", PNG, "image/png")})
    assert r.status_code == 200, r.text
    meta = r.json(); S["files"].add(meta["id"])
    assert meta["content_type"] == "image/png" and meta["size"] == len(PNG)
    got = next(x for x in adm().get(f"{BASE}/invoices").json() if x["id"] == inv["id"])
    assert [f["id"] for f in got["files"]] == [meta["id"]]
    dl = adm().get(f"{BASE}/files/{meta['id']}")
    assert dl.status_code == 200 and dl.content == PNG and dl.headers["content-type"].startswith("image/png")
    assert adm("all").get(f"{BASE}/files/{meta['id']}").status_code == 200
    assert adm(ET).get(f"{BASE}/files/{meta['id']}").status_code == 404
    pdf = adm().post(f"{BASE}/invoices/{inv['id']}/files", files={"file": ("TEST_f.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")})
    assert pdf.status_code == 200
    assert adm().post(f"{BASE}/invoices/{inv['id']}/files", files={"file": ("TEST_x.txt", b"hello", "text/plain")}).status_code == 422
    assert adm().post(f"{BASE}/invoices/{inv['id']}/files", files={"file": ("TEST_e.png", b"", "image/png")}).status_code == 422
    # PUT preserves files
    u = adm().put(f"{BASE}/invoices/{inv['id']}", json={"supplier": "TEST_Tedarik2", "date": T, "amount": 11, "files": []})
    assert u.status_code == 200 and len(u.json()["files"]) == 2
    assert adm().delete(f"{BASE}/invoices/{inv['id']}/files/{meta['id']}").status_code == 200
    assert adm().get(f"{BASE}/files/{meta['id']}").status_code == 404
    got = next(x for x in adm().get(f"{BASE}/invoices").json() if x["id"] == inv["id"])
    assert len(got["files"]) == 1


def test_invoice_file_max_10():
    inv = _new_invoice(amount=10)
    MDB.invoices.update_one({"id": inv["id"]}, {"$set": {"files": [{"id": f"TEST_{i}"} for i in range(10)]}})
    r = adm().post(f"{BASE}/invoices/{inv['id']}/files", files={"file": ("TEST_fatura.png", PNG, "image/png")})
    assert r.status_code == 422


# ---------- Settings ----------
def test_settings_toggle():
    s = adm("all")
    assert s.put(f"{BASE}/settings", json={"product_sales": True}).json() == {"product_sales": True}
    assert adm().get(f"{BASE}/settings").json()["product_sales"] is True
    assert adm().get(f"{BASE}/me").json()["product_sales"] is True
    assert adm().get(f"{BASE}/dashboard").json()["settings"]["product_sales"] is True
    assert s.put(f"{BASE}/settings", json={"product_sales": False}).status_code == 200
    assert adm().get(f"{BASE}/me").json()["product_sales"] is False
    assert s.put(f"{BASE}/settings", json={}).status_code == 422


# ---------- Wizard recipe on existing product ----------
def test_wizard_recipe_existing_product():
    p = adm().post(f"{BASE}/products", json={"name": "TEST_P21_Lahmacun", "category": "Pide", "price": 90})
    assert p.status_code == 200; pid = p.json()["id"]; S["products"].add(pid)
    r = adm().post(f"{BASE}/products/{pid}/wizard-recipe", json={"price": 120, "target_margin": 60,
        "ingredients": [{"name": "TEST_P21_Hamur", "unit": "adet", "unit_cost": 8, "amount": 1}, {"name": "TEST_P21_Kıyma", "unit": "kg", "unit_cost": 400, "amount": 0.05}]})
    assert r.status_code == 200, r.text
    d = r.json()["product"]
    for rid in (FL, ET, DU):
        for i in adm(rid).get(f"{BASE}/inventory").json():
            if i["name"].startswith("TEST_P21_"):
                S["inv"].add(i["id"])
    assert len(r.json()["created_ingredients"]) == 6
    assert d["cost"] == pytest.approx(28) and d["price"] == 120 and d["target_margin"] == 60 and d["name"] == "TEST_P21_Lahmacun" and d["category"] == "Pide"
    got = next(x for x in adm().get(f"{BASE}/products").json() if x["id"] == pid)
    assert len(got["recipe"]) == 2 and got["cost"] == pytest.approx(28)
    assert adm().post(f"{BASE}/products/nope/wizard-recipe", json={"price": 1, "ingredients": [{"name": "a", "unit": "kg", "amount": 1}]}).status_code == 404
    assert adm().post(f"{BASE}/products/{pid}/wizard-recipe", json={"price": 1, "ingredients": []}).status_code == 422


# ---------- Export ----------
def test_export_includes_incomes_and_payment_column():
    inc = adm().post(f"{BASE}/incomes", json={"date": T, "amount": 42, "payment": "Havale", "category": "TEST_EXP"}).json()
    S["incomes"].add(inc["id"])
    x = adm().get(f"{BASE}/reports/export", params={"period": "daily", "format": "xlsx"})
    assert x.status_code == 200
    wb = load_workbook(io.BytesIO(x.content))
    text = " | ".join(str(c) for ws in wb.worksheets for row in ws.iter_rows(values_only=True) for c in row if c is not None)
    assert "Gelir Kayıtları" in text and "TEST_EXP" in text and "Havale" in text and "Gider Kayıtları" in text
    pdf = adm().get(f"{BASE}/reports/export", params={"period": "daily", "format": "pdf"})
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
