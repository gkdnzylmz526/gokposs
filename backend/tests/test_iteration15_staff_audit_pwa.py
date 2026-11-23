# Iteration 15: staff role permissions, staff sale price tamper, inventory count, audit logs, PWA assets.
import os
import time
import uuid

import pytest
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

from conftest import get_token, MEMBER_EMAIL, ADMIN_EMAIL
from clerk_helper import bapi

load_dotenv("/app/backend/.env")
BASE_URL = open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split()[0].rstrip("/")
API = f"{BASE_URL}/api"
STAFF_EMAIL = MEMBER_EMAIL  # this account currently has role 'staff'
PURE_MEMBER_EMAIL = "gokboss-it15-member+clerk_test@example.com"

created = {"products": [], "inventory": [], "sales": []}


def H(email):
    return {"Authorization": f"Bearer {get_token(email)[1]}"}


@pytest.fixture(scope="module", autouse=True)
def fixtures_data():
    a = H(ADMIN_EMAIL)
    inv = requests.post(f"{API}/inventory", json={"name": f"TEST_it15_inv_{uuid.uuid4().hex[:5]}", "quantity": 10, "unit": "kg", "minimum": 2, "unit_cost": 5}, headers=a).json()
    created["inventory"].append(inv["id"])
    prod = requests.post(f"{API}/products", json={"name": f"TEST_it15_prod_{uuid.uuid4().hex[:5]}", "category": "TEST", "price": 120, "cost": 40,
                                                 "recipe": [{"inventory_id": inv["id"], "amount": 0.5}]}, headers=a).json()
    created["products"].append(prod["id"])
    yield {"inv": inv, "prod": prod}
    for sid in created["sales"]:
        requests.delete(f"{API}/sales/{sid}", headers=a)
    for pid in created["products"]:
        requests.delete(f"{API}/products/{pid}", headers=a)
    for iid in created["inventory"]:
        requests.delete(f"{API}/inventory/{iid}", headers=a)


# --- Staff permissions
class TestStaffPermissions:
    def test_me_staff(self):
        r = requests.get(f"{API}/me", headers=H(STAFF_EMAIL))
        assert r.status_code == 200 and r.json()["role"] == "staff"

    def test_staff_view_no_cost(self, fixtures_data):
        r = requests.get(f"{API}/staff-view", headers=H(STAFF_EMAIL))
        assert r.status_code == 200
        d = r.json()
        p = next(x for x in d["products"] if x["id"] == fixtures_data["prod"]["id"])
        assert "cost" not in p and p["price"] == 120
        i = next(x for x in d["inventory"] if x["id"] == fixtures_data["inv"]["id"])
        assert set(i.keys()) == {"id", "name", "quantity", "unit", "minimum"}

    @pytest.mark.parametrize("method,path", [("GET", "/dashboard"), ("GET", "/reports"), ("GET", "/sales"), ("GET", "/expenses"),
                                             ("POST", "/products"), ("GET", "/audit-logs"), ("GET", "/users"), ("GET", "/inventory"),
                                             ("GET", "/stock-movements"), ("GET", "/payroll"), ("DELETE", "/sales/x"), ("PUT", "/sales/x")])
    def test_staff_forbidden(self, method, path):
        r = requests.request(method, f"{API}{path}", json={"name": "TEST_x"}, headers=H(STAFF_EMAIL))
        assert r.status_code == 403, (method, path, r.status_code)

    def test_staff_inventory_put_403(self, fixtures_data):
        inv = fixtures_data["inv"]
        r = requests.put(f"{API}/inventory/{inv['id']}", json={**inv, "quantity": 999}, headers=H(STAFF_EMAIL))
        assert r.status_code == 403

    def test_staff_patch_role_403(self):
        uid = get_token(STAFF_EMAIL)[0]
        r = requests.patch(f"{API}/users/{uid}/role", json={"role": "admin"}, headers=H(STAFF_EMAIL))
        assert r.status_code == 403


# --- Staff sale price tamper
class TestStaffSales:
    def test_tamper_price(self, fixtures_data):
        prod = fixtures_data["prod"]
        r = requests.post(f"{API}/sales", json={"product_id": prod["id"], "product_name": "HACK", "quantity": 2, "unit_price": 1, "unit_cost": 0, "amount": 2, "channel": "Paket"}, headers=H(STAFF_EMAIL))
        assert r.status_code == 200, r.text
        s = r.json()
        created["sales"].append(s["id"])
        assert s["amount"] == 240 and s["unit_price"] == 120 and s["product_name"] == prod["name"] and s["channel"] == "Paket"
        stored = next(x for x in requests.get(f"{API}/sales", headers=H(ADMIN_EMAIL)).json() if x["id"] == s["id"])
        assert stored["amount"] == 240
        inv = next(x for x in requests.get(f"{API}/inventory", headers=H(ADMIN_EMAIL)).json() if x["id"] == fixtures_data["inv"]["id"])
        assert inv["quantity"] == 9  # 10 - 2*0.5

    def test_missing_product_422(self):
        r = requests.post(f"{API}/sales", json={"product_name": "TEST_nope", "quantity": 1, "unit_price": 50}, headers=H(STAFF_EMAIL))
        assert r.status_code == 422
        r2 = requests.post(f"{API}/sales", json={"product_id": "does-not-exist", "quantity": 1}, headers=H(STAFF_EMAIL))
        assert r2.status_code == 422

    def test_response_leaks_cost(self, fixtures_data):
        # Informational: staff POST /sales response should ideally not expose unit_cost
        r = requests.post(f"{API}/sales", json={"product_id": fixtures_data["prod"]["id"], "quantity": 1}, headers=H(STAFF_EMAIL))
        created["sales"].append(r.json()["id"])
        print("staff sale response unit_cost:", r.json().get("unit_cost"))

    def test_negative_quantity_staff(self, fixtures_data):
        r = requests.post(f"{API}/sales", json={"product_id": fixtures_data["prod"]["id"], "quantity": -5}, headers=H(STAFF_EMAIL))
        if r.status_code == 200:
            created["sales"].append(r.json()["id"])
        print("negative qty staff sale:", r.status_code, r.json().get("amount"))
        assert r.status_code == 422, "staff can post negative-quantity sale (negative revenue + stock increase)"


# --- Stock count
class TestCount:
    def test_count_negative_422(self, fixtures_data):
        r = requests.post(f"{API}/inventory/{fixtures_data['inv']['id']}/count", json={"quantity": -1}, headers=H(STAFF_EMAIL))
        assert r.status_code == 422

    def test_count_unknown_404(self):
        r = requests.post(f"{API}/inventory/nope-{uuid.uuid4().hex[:6]}/count", json={"quantity": 1}, headers=H(STAFF_EMAIL))
        assert r.status_code == 404

    def test_count_ok_and_movement(self, fixtures_data):
        iid = fixtures_data["inv"]["id"]
        r = requests.post(f"{API}/inventory/{iid}/count", json={"quantity": 7.25}, headers=H(STAFF_EMAIL))
        assert r.status_code == 200 and r.json()["quantity"] == 7.25
        mv = requests.get(f"{API}/stock-movements", params={"inventory_id": iid}, headers=H(ADMIN_EMAIL)).json()
        assert mv[0]["reason"] == "Stok sayımı" and mv[0]["quantity_after"] == 7.25
        inv = next(x for x in requests.get(f"{API}/staff-view", headers=H(STAFF_EMAIL)).json()["inventory"] if x["id"] == iid)
        assert inv["quantity"] == 7.25


# --- Audit logs
class TestAudit:
    def test_audit_entries(self, fixtures_data):
        a = H(ADMIN_EMAIL)
        # self-contained (xdist may run classes on different workers)
        assert requests.post(f"{API}/inventory/{fixtures_data['inv']['id']}/count", json={"quantity": 4}, headers=H(STAFF_EMAIL)).status_code == 200
        s = requests.post(f"{API}/sales", json={"product_id": fixtures_data["prod"]["id"], "quantity": 1}, headers=H(STAFF_EMAIL)).json()
        created["sales"].append(s["id"])
        logs = requests.get(f"{API}/audit-logs", params={"limit": 500}, headers=a).json()
        admin_adds = [l for l in logs if l["item_id"] == fixtures_data["prod"]["id"] and l["action"] == "Ekledi"]
        assert admin_adds and admin_adds[0]["user_email"] == ADMIN_EMAIL and admin_adds[0]["role"] == "admin" and admin_adds[0]["collection"] == "products"
        counts = [l for l in logs if l["item_id"] == fixtures_data["inv"]["id"] and l["action"] == "Saydı"]
        assert counts and counts[0]["user_email"] == STAFF_EMAIL and counts[0]["role"] == "staff" and "→" in counts[0]["summary"]
        sale_ids = {s["id"]}
        staff_sales = [l for l in logs if l["item_id"] in sale_ids and l["collection"] == "sales"]
        assert staff_sales and all(l["user_email"] == STAFF_EMAIL for l in staff_sales)
        for l in logs[:5]:
            assert "_id" not in l and {"user_email", "role", "action", "collection", "item_id", "summary", "created_at"} <= set(l)

    def test_update_delete_audit(self, fixtures_data):
        a = H(ADMIN_EMAIL)
        inv = requests.post(f"{API}/inventory", json={"name": "TEST_it15_tmp", "quantity": 0}, headers=a).json()
        inv2 = {**inv, "name": "TEST_it15_tmp2"}
        assert requests.put(f"{API}/inventory/{inv['id']}", json=inv2, headers=a).status_code == 200
        assert requests.delete(f"{API}/inventory/{inv['id']}", headers=a).status_code == 200
        logs = requests.get(f"{API}/audit-logs", params={"collection": "inventory"}, headers=a).json()
        actions = {l["action"] for l in logs if l["item_id"] == inv["id"]}
        assert actions == {"Ekledi", "Düzenledi", "Sildi"}

    def test_filters(self):
        a = H(ADMIN_EMAIL)
        logs = requests.get(f"{API}/audit-logs", params={"collection": "sales"}, headers=a).json()
        assert logs and all(l["collection"] == "sales" for l in logs)
        logs = requests.get(f"{API}/audit-logs", params={"user_email": STAFF_EMAIL}, headers=a).json()
        assert logs and all(l["user_email"] == STAFF_EMAIL for l in logs)
        logs = requests.get(f"{API}/audit-logs", params={"limit": 3}, headers=a).json()
        assert len(logs) <= 3
        times = [l["created_at"] for l in requests.get(f"{API}/audit-logs", headers=a).json()]
        assert times == sorted(times, reverse=True)
        assert requests.get(f"{API}/audit-logs", params={"limit": 0}, headers=a).status_code == 422

    def test_member_cannot_read(self):
        r = requests.get(f"{API}/me", headers=H(PURE_MEMBER_EMAIL))
        assert r.status_code == 200 and r.json()["role"] == "member"
        assert requests.get(f"{API}/audit-logs", headers=H(PURE_MEMBER_EMAIL)).status_code == 403
        assert requests.get(f"{API}/staff-view", headers=H(PURE_MEMBER_EMAIL)).status_code == 403
        assert requests.post(f"{API}/sales", json={"product_id": "x"}, headers=H(PURE_MEMBER_EMAIL)).status_code == 403


# --- PWA assets
class TestPWA:
    def test_manifest(self):
        r = requests.get(f"{BASE_URL}/manifest.json")
        assert r.status_code == 200
        m = r.json()
        assert m["name"] == "GÖKBOSS POS" and m["display"] == "standalone"
        srcs = {i["src"] for i in m["icons"]}
        assert {"/icon-192.png", "/icon-512.png"} <= srcs

    @pytest.mark.parametrize("path", ["/icon-192.png", "/icon-512.png", "/apple-touch-icon.png"])
    def test_icons(self, path):
        r = requests.get(f"{BASE_URL}{path}")
        assert r.status_code == 200 and r.headers["content-type"].startswith("image/png")

    def test_sw(self):
        r = requests.get(f"{BASE_URL}/sw.js")
        assert r.status_code == 200 and "javascript" in r.headers["content-type"] and "addEventListener" in r.text

    def test_index_html(self):
        t = requests.get(f"{BASE_URL}/").text
        assert '<html lang="tr"' in t and "<title>GÖKBOSS POS</title>" in t and "apple-touch-icon" in t and "manifest.json" in t
