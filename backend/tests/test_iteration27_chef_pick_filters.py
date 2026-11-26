# Iteration 27: Günün önerisi (/api/chef-pick GET/PUT/DELETE + /api/public/menu chef_pick), tag data for QR filters, GÖKPOS brand in mailer.
# Run with: pytest tests/test_iteration27_chef_pick_filters.py -n 0 -v   (ordered, shared state; cleans up its TEST_ products + chef pick)
import os
import sys

import pymongo
import requests

from conftest import get_token, ADMIN_EMAIL

BASE = open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split()[0].rstrip("/") + "/api"
FL = "florya-tasfirin"
S = {"ids": {}}
ENV = dict(l.split("=", 1) for l in open("/app/backend/.env").read().splitlines() if "=" in l)
DB = pymongo.MongoClient(ENV["MONGO_URL"].strip('"'))[ENV["DB_NAME"].strip('"')]


def adm():
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {get_token(ADMIN_EMAIL)[1]}", "X-Restaurant": FL})
    return s


def public_menu(lang="tr"):
    return requests.get(f"{BASE}/public/menu", params={"lang": lang}, headers={"X-No-Auth": "1"}, timeout=90)


# --- setup: TEST_ products with tags
def test_00_create_tagged_products():
    s = adm()
    for name, cat, tags, active in (("TEST_Falafel", "TEST_Vegan", ["vegan"], True), ("TEST_Acili Durum", "TEST_Vegan", ["spicy"], True),
                                    ("TEST_Baklava", "TEST_Tatli", ["nuts", "dairy"], True), ("TEST_Pasif", "TEST_Tatli", ["vegan"], False)):
        r = s.post(f"{BASE}/products", json={"name": name, "price": 99, "category": cat, "active": active, "tags": tags})
        assert r.status_code in (200, 201), r.text
        assert r.json()["tags"] == tags
        S["ids"][name] = r.json()["id"]


def test_01_public_menu_tags_present_and_no_pick():
    r = public_menu()
    assert r.status_code == 200
    d = r.json()
    items = {i["name"]: i for c in d["categories"] for i in c["items"]}
    assert items["TEST_Falafel"]["tags"] == ["vegan"]
    assert "TEST_Pasif" not in items
    assert d["chef_pick"] is None


# --- chef pick CRUD
def test_02_put_unknown_and_inactive_404():
    s = adm()
    assert s.put(f"{BASE}/chef-pick", json={"product_id": "nope-xyz"}).status_code == 404
    assert s.put(f"{BASE}/chef-pick", json={"product_id": S["ids"]["TEST_Pasif"]}).status_code == 404
    assert s.put(f"{BASE}/chef-pick", json={"product_id": S["ids"]["TEST_Falafel"], "note": "x" * 121}).status_code == 422


def test_03_put_and_get():
    s = adm()
    r = s.put(f"{BASE}/chef-pick", json={"product_id": S["ids"]["TEST_Falafel"], "note": "  bugün taze nohutla  "})
    assert r.status_code == 200, r.text
    assert r.json()["note"] == "bugün taze nohutla" and r.json()["today"] is True
    g = s.get(f"{BASE}/chef-pick").json()
    assert g["product_id"] == S["ids"]["TEST_Falafel"] and g["today"] is True


def test_04_public_menu_has_pick():
    d = public_menu().json()
    p = d["chef_pick"]
    assert p and p["name"] == "TEST_Falafel" and p["price"] == 99 and p["tags"] == ["vegan"]
    assert p["note"] == "bugün taze nohutla"
    assert d["categories"][p["category_index"]]["category"] == "TEST_Vegan"
    assert "id" not in p


def test_05_public_menu_pick_translated_en():
    p = public_menu("en").json()["chef_pick"]
    assert p and p["note"] and p["note"] != "bugün taze nohutla", p
    print("EN note:", p["note"], "| name:", p["name"])


def test_06_stale_date_hidden():
    DB.settings.update_one({"id": "chef_pick"}, {"$set": {"date": "2000-01-01"}})
    assert public_menu().json()["chef_pick"] is None
    assert adm().get(f"{BASE}/chef-pick").json()["today"] is False


def test_07_pick_product_deactivated_hidden():
    s = adm()
    assert s.put(f"{BASE}/chef-pick", json={"product_id": S["ids"]["TEST_Baklava"]}).status_code == 200
    assert public_menu().json()["chef_pick"]["name"] == "TEST_Baklava"
    r = s.put(f"{BASE}/products/{S['ids']['TEST_Baklava']}", json={"name": "TEST_Baklava", "price": 99, "category": "TEST_Tatli", "active": False, "tags": ["nuts", "dairy"]})
    assert r.status_code == 200, r.text
    assert public_menu().json()["chef_pick"] is None
    s.put(f"{BASE}/products/{S['ids']['TEST_Baklava']}", json={"name": "TEST_Baklava", "price": 99, "category": "TEST_Tatli", "active": True, "tags": ["nuts", "dairy"]})


def test_08_delete_clears():
    s = adm()
    assert s.delete(f"{BASE}/chef-pick").status_code == 200
    g = s.get(f"{BASE}/chef-pick").json()
    assert g["product_id"] == "" and g["today"] is False
    assert public_menu().json()["chef_pick"] is None


def test_09_requires_auth():
    assert requests.get(f"{BASE}/chef-pick", headers={"X-No-Auth": "1"}).status_code in (401, 403)
    assert requests.put(f"{BASE}/chef-pick", json={"product_id": "x"}, headers={"X-No-Auth": "1"}).status_code in (401, 403)
    assert requests.delete(f"{BASE}/chef-pick", headers={"X-No-Auth": "1"}).status_code in (401, 403)


def test_10_mailer_brand():
    src = open("/app/backend/mailer.py").read()
    assert "GÖKBOSS" not in src and 'From"] = f"GÖKPOS' in src


def test_99_cleanup():
    s = adm()
    s.delete(f"{BASE}/chef-pick")
    for pid in S["ids"].values():
        assert s.delete(f"{BASE}/products/{pid}").status_code in (200, 204, 404)
