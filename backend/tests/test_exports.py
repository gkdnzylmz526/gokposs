# Iteration 4: report export (xlsx/pdf), dashboard weekly, reports shape, cash reconciliation
import io
import os

import pytest
import requests
from openpyxl import load_workbook

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
SECTIONS = ["Dönem Özeti", "Kasa Mutabakatı", "Ürün Performansı", "Satış Kayıtları", "Gider Kayıtları"]


@pytest.fixture(scope="module")
def s():
    return requests.Session()


@pytest.fixture(scope="module")
def created(s):
    ids = []
    yield ids
    for coll, _id in ids:
        s.delete(f"{BASE_URL}/api/{coll}/{_id}", timeout=15)


def _post(s, created, coll, payload):
    r = s.post(f"{BASE_URL}/api/{coll}", json=payload, timeout=15)
    assert r.status_code == 200, r.text
    created.append((coll, r.json()["id"]))
    return r.json()


@pytest.fixture(scope="module")
def seeded(s, created):
    _post(s, created, "sales", {"product_name": "TEST_Çiğ köfte Şiş İğne", "quantity": 2, "unit_price": 150, "unit_cost": 40, "amount": 300, "channel": "Paket"})
    _post(s, created, "expenses", {"category": "TEST_Gıda", "amount": 75.5, "note": "TEST_ağır yük ÜÇÖ"})
    c1 = _post(s, created, "cash", {"opening": 1000, "closing": 1100, "note": "TEST_ilk"})
    c2 = _post(s, created, "cash", {"opening": 5000, "closing": 1600, "note": "TEST_son"})
    return c1, c2


# Dashboard
def test_dashboard_weekly(s, seeded):
    d = s.get(f"{BASE_URL}/api/dashboard", timeout=15).json()
    assert len(d["weekly"]) == 7
    assert d["weekly"][-1]["revenue"] == d["revenue"]
    assert d["profit"] == d["revenue"] - d["expenses"]
    assert d["revenue"] >= 300


# Reports shape
@pytest.mark.parametrize("period", ["daily", "weekly", "monthly"])
def test_reports_shape(s, seeded, period):
    r = s.get(f"{BASE_URL}/api/reports", params={"period": period}, timeout=15).json()
    for k in ("start", "end", "sales", "expenses_list", "top_products", "revenue", "expenses", "profit", "sales_count"):
        assert k in r
    assert any(p["product_name"] == "TEST_Çiğ köfte Şiş İğne" for p in r["top_products"])


# Cash reconciliation: opening from earliest, closing from latest
def test_reconciliation(s, seeded):
    r = s.get(f"{BASE_URL}/api/cash/reconciliation", timeout=15).json()
    cash = s.get(f"{BASE_URL}/api/cash", timeout=15).json()
    today = r["date"]
    todays = [c for c in cash if c["created_at"][:10] == today]
    earliest = min(todays, key=lambda c: c["created_at"])
    latest = max(todays, key=lambda c: c["created_at"])
    assert r["opening"] == earliest["opening"]
    assert r["actual_closing"] == latest["closing"]
    assert r["expected_closing"] == pytest.approx(r["opening"] + r["sales"] - r["expenses"])
    assert r["difference"] == pytest.approx(r["actual_closing"] - r["expected_closing"])


# Excel export
@pytest.mark.parametrize("period", ["daily", "weekly", "monthly"])
def test_excel_export(s, seeded, period):
    r = s.get(f"{BASE_URL}/api/reports/export", params={"period": period, "format": "xlsx"}, timeout=30)
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers["content-type"]
    assert "attachment" in r.headers["content-disposition"] and ".xlsx" in r.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(r.content))
    ws = wb.active
    values = [c.value for row in ws.iter_rows() for c in row if c.value is not None]
    texts = [str(v) for v in values]
    for sec in SECTIONS:
        assert any(t.startswith(sec) for t in texts), sec
    rep = s.get(f"{BASE_URL}/api/reports", params={"period": period}, timeout=15).json()
    rows = {row[0].value: row[1].value for row in ws.iter_rows() if row[0].value}
    assert rows["Toplam ciro"] == rep["revenue"]
    assert rows["Toplam gider"] == rep["expenses"]
    assert rows["Net kâr"] == rep["profit"]
    assert rows["Satış adedi (işlem)"] == rep["sales_count"]
    assert "TEST_Çiğ köfte Şiş İğne" in texts
    assert "TEST_ağır yük ÜÇÖ" in texts


# PDF export with Turkish characters
@pytest.mark.parametrize("period", ["daily", "weekly", "monthly"])
def test_pdf_export(s, seeded, period):
    import fitz
    r = s.get(f"{BASE_URL}/api/reports/export", params={"period": period, "format": "pdf"}, timeout=30)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert "attachment" in r.headers["content-disposition"]
    assert r.content[:4] == b"%PDF"
    doc = fitz.open(stream=r.content, filetype="pdf")
    text = " ".join(" ".join(p.get_text() for p in doc).split())
    for sec in SECTIONS:
        assert sec in text, sec
    for token in ("GÖKBOSS", "Çiğ köfte Şiş İğne", "ağır yük ÜÇÖ", "₺", "Açılış kasası", "Kâr"):
        assert token in text, token


# Validation
@pytest.mark.parametrize("params", [{"period": "yearly", "format": "pdf"}, {"period": "daily", "format": "csv"}])
def test_export_invalid(s, params):
    assert s.get(f"{BASE_URL}/api/reports/export", params=params, timeout=15).status_code == 422


# Special XML chars in user data should not break PDF
def test_pdf_special_chars(s, created):
    _post(s, created, "expenses", {"category": "TEST_A&B <x>", "amount": 1, "note": "TEST_5 < 6 & ok"})
    r = s.get(f"{BASE_URL}/api/reports/export", params={"period": "daily", "format": "pdf"}, timeout=30)
    assert r.status_code == 200, r.text[:300]
