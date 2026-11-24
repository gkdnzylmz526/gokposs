# Iteration 20: POST /api/products/wizard (guided product + recipe; new ingredients opened in all 3 restaurants).
# Ordered shared state; run with -n 0. Cleans TEST_ products and TEST_ inventory it created (by id).
import pytest
import requests
from pymongo import MongoClient

from conftest import get_token, ADMIN_EMAIL

BASE = open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split()[0].rstrip("/") + "/api"
FL, ET, DU = "florya-tasfirin", "etiler-marmaris", "durumtir"
RIDS = (FL, ET, DU)
ENV = dict(l.strip().split("=", 1) for l in open("/app/backend/.env") if "=" in l)
MDB = MongoClient(ENV["MONGO_URL"].strip('"'))[ENV["DB_NAME"].strip('"')]
S = {"prods": set(), "inv": set()}


def adm(rid):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {get_token(ADMIN_EMAIL)[1]}", "X-Restaurant": rid})
    return s


def inv_by_name(rid, name):
    return [i for i in adm(rid).get(f"{BASE}/inventory").json() if i["name"].lower() == name.lower()]


def track_inv(name):
    for rid in RIDS:
        for i in inv_by_name(rid, name):
            S["inv"].add(i["id"])


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    for p in S["prods"]:
        print("del prod", adm(FL).delete(f"{BASE}/products/{p}").status_code)
    MDB.stock_movements.delete_many({"inventory_id": {"$in": list(S["inv"])}})
    print("del inv", MDB.inventory.delete_many({"id": {"$in": list(S["inv"])}, "name": {"$regex": "^TEST_", "$options": "i"}}).deleted_count)


def test_wizard_new_ingredients_all_restaurants_and_cost():
    r = adm(FL).post(f"{BASE}/products/wizard", json={"name": "TEST_P20_Pide", "category": "Pide", "price": 143, "target_margin": 65,
        "ingredients": [{"name": "TEST_P20_Hamur", "unit": "adet", "unit_cost": 10, "amount": 1},
                        {"name": "TEST_P20_Kıyma", "unit": "kg", "unit_cost": 500, "amount": 0.08}]})
    assert r.status_code == 200, r.text
    d = r.json()
    S["prods"].add(d["product"]["id"])
    track_inv("TEST_P20_Hamur"); track_inv("TEST_P20_Kıyma")
    assert d["product"]["cost"] == pytest.approx(50)
    assert d["product"]["price"] == 143 and d["product"]["category"] == "Pide"
    assert len(d["created_ingredients"]) == 6
    for rid in RIDS:
        h = inv_by_name(rid, "TEST_P20_Hamur"); k = inv_by_name(rid, "TEST_P20_Kıyma")
        assert len(h) == 1 and h[0]["unit"] == "adet" and h[0]["unit_cost"] == 10 and h[0]["quantity"] == 0, (rid, h)
        assert len(k) == 1 and k[0]["unit"] == "kg" and k[0]["unit_cost"] == 500 and k[0]["quantity"] == 0, (rid, k)
    p = next(x for x in adm(FL).get(f"{BASE}/products").json() if x["id"] == d["product"]["id"])
    assert p["cost"] == pytest.approx(50) and len(p["recipe"]) == 2
    fl_ids = {i["id"] for i in adm(FL).get(f"{BASE}/inventory").json()}
    assert all(x["inventory_id"] in fl_ids for x in p["recipe"])


def test_wizard_duplicate_409_turkish_case():
    r = adm(FL).post(f"{BASE}/products/wizard", json={"name": "TEST_P20_PİDE", "price": 10,
        "ingredients": [{"name": "TEST_P20_Hamur", "amount": 1}]})
    assert r.status_code == 409, r.text


def test_wizard_reuses_existing_case_insensitive_fills_missing_and_zero_cost():
    # existing only in ET with zero cost
    e = adm(ET).post(f"{BASE}/inventory", json={"name": "TEST_P20_Şeker", "quantity": 4, "unit": "kg", "unit_cost": 0})
    assert e.status_code == 200, e.text
    S["inv"].add(e.json()["id"])
    r = adm(ET).post(f"{BASE}/products/wizard", json={"name": "TEST_P20_Tatlı", "category": "Tatlı", "price": 50,
        "ingredients": [{"name": "test_p20_şeker", "unit": "gr", "unit_cost": 40, "amount": 0.1},
                        {"name": "TEST_P20_KIYMA", "unit": "kg", "amount": 0.1}]})
    assert r.status_code == 200, r.text
    d = r.json(); S["prods"].add(d["product"]["id"])
    track_inv("TEST_P20_Şeker")
    assert d["product"]["cost"] == pytest.approx(4 + 50)
    # Kıyma existed everywhere -> no new; Şeker created in FL and DU only
    assert len(d["created_ingredients"]) == 2, d["created_ingredients"]
    for rid in RIDS:
        s = inv_by_name(rid, "TEST_P20_Şeker")
        assert len(s) == 1 and s[0]["unit"] == "kg" and s[0]["unit_cost"] == 40, (rid, s)
        assert len([i for i in adm(rid).get(f"{BASE}/inventory").json() if "kıyma" in i["name"].lower() and i["name"].startswith("TEST_P20")]) == 1
    et = inv_by_name(ET, "TEST_P20_Şeker")[0]
    assert et["id"] == e.json()["id"] and et["quantity"] == 4
    et_ids = {i["id"] for i in adm(ET).get(f"{BASE}/inventory").json()}
    assert all(x["inventory_id"] in et_ids for x in d["product"]["recipe"])


def test_wizard_all_mode():
    r = adm("all").post(f"{BASE}/products/wizard", json={"name": "TEST_P20_Ayran", "category": "İçecek", "price": 30,
        "ingredients": [{"name": "TEST_P20_Yoğurt", "unit": "kg", "unit_cost": 100, "amount": 0.2}]})
    assert r.status_code == 200, r.text
    d = r.json(); S["prods"].add(d["product"]["id"]); track_inv("TEST_P20_Yoğurt")
    assert d["product"]["cost"] == pytest.approx(20)
    for rid in RIDS:
        assert len(inv_by_name(rid, "TEST_P20_Yoğurt")) == 1
    fl_ids = {i["id"] for i in adm(FL).get(f"{BASE}/inventory").json()}
    assert d["product"]["recipe"][0]["inventory_id"] in fl_ids


def test_wizard_validation():
    s = adm(FL)
    assert s.post(f"{BASE}/products/wizard", json={"name": "TEST_P20_X", "price": 10, "ingredients": []}).status_code == 422
    assert s.post(f"{BASE}/products/wizard", json={"name": "", "price": 10, "ingredients": [{"name": "a", "amount": 1}]}).status_code == 422
    assert s.post(f"{BASE}/products/wizard", json={"name": "TEST_P20_X", "price": 10, "ingredients": [{"name": "a", "amount": 0}]}).status_code == 422
    assert s.post(f"{BASE}/products/wizard", json={"name": "TEST_P20_X", "price": 10, "target_margin": 100, "ingredients": [{"name": "a", "amount": 1}]}).status_code == 422
    assert s.post(f"{BASE}/products/wizard", headers={"X-No-Auth": "1"}, json={"name": "TEST_P20_X", "price": 10, "ingredients": [{"name": "a", "amount": 1}]}).status_code in (401, 403)
