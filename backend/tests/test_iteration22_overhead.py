# Iteration 22: fixed-cost (overhead) allocation by revenue ratio -> /api/overhead + /api/product-costs overhead fields.
# Ordered shared state; run with -n 0. Deletes settings {id:'overhead'} at the end.
import math

import pytest
import requests
from pymongo import MongoClient

from conftest import get_token, ADMIN_EMAIL, MEMBER_EMAIL

BASE = open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split()[0].rstrip("/") + "/api"
ENV = dict(l.strip().split("=", 1) for l in open("/app/backend/.env") if "=" in l)
MDB = MongoClient(ENV["MONGO_URL"].strip('"'))[ENV["DB_NAME"].strip('"')]
DEFAULTS = ["Kira", "Elektrik", "Su", "Doğalgaz", "İnternet / telefon", "Personel maaşları", "SGK / vergi", "Muhasebe", "Diğer"]


def adm(rid="florya-tasfirin"):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {get_token(ADMIN_EMAIL)[1]}", "X-Restaurant": rid})
    return s


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    MDB.settings.delete_one({"id": "overhead"})
    yield
    MDB.settings.delete_one({"id": "overhead"})


def test_get_defaults():
    d = adm().get(f"{BASE}/overhead").json()
    assert [i["name"] for i in d["items"]] == DEFAULTS
    assert all(i["amount"] == 0 for i in d["items"])
    assert d["total"] == 0 and d["ratio_pct"] == 0 and d["revenue_source"] == "auto"
    assert d["revenue_manual"] == 0 and d["revenue_used"] == d["revenue_auto"]
    print("auto revenue", d["revenue_auto"])


def test_auto_revenue_matches_db():
    from datetime import datetime, timezone, timedelta
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    exp = sum(float(r.get("amount", 0)) for c in ("sales", "incomes") for r in MDB[c].find({"created_at": {"$gte": since}}))
    d = adm("all").get(f"{BASE}/overhead").json()
    assert abs(d["revenue_auto"] - round(exp, 2)) < 1


def test_negative_422():
    r = adm("all").put(f"{BASE}/overhead", json={"items": [{"name": "Kira", "amount": -5}], "monthly_revenue": 0})
    assert r.status_code == 422
    r = adm("all").put(f"{BASE}/overhead", json={"items": [{"name": "Kira", "amount": 5}], "monthly_revenue": -1})
    assert r.status_code == 422


def test_put_all_mode_and_ratio():
    r = adm("all").put(f"{BASE}/overhead", json={"items": [{"name": "Kira", "amount": 60000}, {"name": "Elektrik", "amount": 30000}], "monthly_revenue": 300000})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["total"] == 90000 and d["ratio_pct"] == 30 and d["revenue_source"] == "manual" and d["revenue_used"] == 300000
    g = adm("etiler-marmaris").get(f"{BASE}/overhead").json()
    assert g["ratio_pct"] == 30 and len(g["items"]) == 2


def test_product_costs_adana():
    d = adm().get(f"{BASE}/product-costs").json()
    assert d["overhead"]["ratio_pct"] == 30
    p = next(x for x in d["products"] if x["name"].lower() == "adana")
    print(p)
    assert p["price"] == 530 and p["cost"] == 100
    assert p["overhead_cost"] == 159 and p["full_cost"] == 259 and p["net_profit"] == 271
    assert p["net_margin"] == 51.1
    tm = p["target_margin"]
    room = 1 - tm / 100 - 0.3
    exp = math.ceil(round(100 / room, 6)) if room > 0.01 else None
    assert p["suggested_with_overhead"] == exp
    if tm == 65:
        assert p["suggested_with_overhead"] == 2000
    for x in d["products"]:
        assert x["full_cost"] == round(x["cost"] + x["overhead_cost"], 2)
    assert "losing" in d["summary"]
    print("summary", d["summary"])


def test_impossible_suggested_none():
    adm("all").put(f"{BASE}/overhead", json={"items": [{"name": "Kira", "amount": 120000}], "monthly_revenue": 300000})  # 40% + 65 > 100
    d = adm().get(f"{BASE}/product-costs").json()
    p = next(x for x in d["products"] if x["name"].lower() == "adana")
    if p["target_margin"] >= 60:
        assert p["suggested_with_overhead"] is None


def test_blank_names_dropped_and_auto_fallback():
    d = adm("all").put(f"{BASE}/overhead", json={"items": [{"name": "Kira", "amount": 1000}, {"name": "   ", "amount": 500}], "monthly_revenue": 0}).json()
    assert len(d["items"]) == 1 and d["total"] == 1000 and d["revenue_source"] == "auto"


def test_member_forbidden(member_auth):
    r = requests.get(f"{BASE}/overhead", headers={"Authorization": f"Bearer {member_auth[1]}", "X-No-Auth": "1"})
    assert r.status_code in (401, 403)
