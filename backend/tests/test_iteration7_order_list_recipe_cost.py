# Iteration 7: automatic order list + recipe cost auto-calc
import os
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


def get_product(s, pid):
    return next(p for p in s.get(f"{BASE_URL}/api/products").json() if p["id"] == pid)


def order_list(s):
    r = s.get(f"{BASE_URL}/api/order-list")
    assert r.status_code == 200
    return r.json()


def find_item(groups, inv_id):
    for g in groups:
        for i in g["items"]:
            if i["inventory_id"] == inv_id:
                return g, i
    return None, None


# Inventory new fields persist
def test_inventory_fields(s):
    a = create(s, "inventory", {"name": f"TEST_Kiyma_{SUFFIX}", "quantity": 3, "unit": "kg", "minimum": 5, "target": 20, "unit_cost": 450.5, "supplier": f"TEST_Kasap_{SUFFIX}"})
    assert a["unit_cost"] == 450.5 and a["target"] == 20 and a["supplier"] == f"TEST_Kasap_{SUFFIX}"
    r = s.put(f"{BASE_URL}/api/inventory/{a['id']}", json={**a, "unit_cost": 500, "supplier": f"TEST_Kasap2_{SUFFIX}"})
    assert r.status_code == 200
    cur = next(i for i in s.get(f"{BASE_URL}/api/inventory").json() if i["id"] == a["id"])
    assert cur["unit_cost"] == 500 and cur["supplier"] == f"TEST_Kasap2_{SUFFIX}" and cur["target"] == 20


# Order list calculation and grouping
def test_order_list(s):
    sup = f"TEST_Manav_{SUFFIX}"
    t = create(s, "inventory", {"name": f"TEST_Domates_{SUFFIX}", "quantity": 2, "unit": "kg", "minimum": 5, "target": 15, "unit_cost": 30, "supplier": sup})
    nt = create(s, "inventory", {"name": f"TEST_Biber_{SUFFIX}", "quantity": 1, "unit": "kg", "minimum": 4, "target": 0, "unit_cost": 40, "supplier": sup})
    eq = create(s, "inventory", {"name": f"TEST_Sogan_{SUFFIX}", "quantity": 4, "unit": "kg", "minimum": 4, "unit_cost": 10, "supplier": sup})
    neg = create(s, "inventory", {"name": f"TEST_Tuz_{SUFFIX}", "quantity": 3, "unit": "kg", "minimum": 5, "target": 2, "unit_cost": 5})
    ok = create(s, "inventory", {"name": f"TEST_Un_{SUFFIX}", "quantity": 50, "unit": "kg", "minimum": 5, "unit_cost": 20, "supplier": sup})
    groups = order_list(s)
    g, i = find_item(groups, t["id"])
    assert g["supplier"] == sup and i["suggested"] == 13 and i["estimated_cost"] == 390
    _, i2 = find_item(groups, nt["id"])
    assert i2["suggested"] == 7 and i2["estimated_cost"] == 280  # 4*2-1
    _, i3 = find_item(groups, eq["id"])
    assert i3 is not None and i3["suggested"] == 4  # at minimum is included
    gn, i4 = find_item(groups, neg["id"])
    assert i4["suggested"] == 0 and i4["estimated_cost"] == 0
    assert gn["supplier"] == "Tedarikçi belirtilmemiş"
    assert find_item(groups, ok["id"]) == (None, None)
    assert g["estimated_total"] == round(sum(x["estimated_cost"] for x in g["items"]), 2)
    assert g["estimated_total"] == 390 + 280 + 40
    for k in ["inventory_id", "name", "unit", "quantity", "minimum", "suggested", "estimated_cost"]:
        assert k in i
    names = [x["supplier"] for x in groups]
    assert names == sorted(names)


# Recipe cost auto-calc + recompute on ingredient update/delete
def test_recipe_cost(s):
    a = create(s, "inventory", {"name": f"TEST_Kofte_{SUFFIX}", "quantity": 10, "unit": "kg", "minimum": 1, "unit_cost": 400})
    b = create(s, "inventory", {"name": f"TEST_Ekmek_{SUFFIX}", "quantity": 100, "unit": "adet", "minimum": 5, "unit_cost": 5})
    p = create(s, "products", {"name": f"TEST_Burger_{SUFFIX}", "price": 200, "cost": 999,
                               "recipe": [{"inventory_id": a["id"], "amount": 0.15}, {"inventory_id": b["id"], "amount": 1}]})
    assert p["cost"] == 65 and p["cost_from_recipe"] is True
    assert get_product(s, p["id"])["cost"] == 65
    m = create(s, "products", {"name": f"TEST_Cay_{SUFFIX}", "price": 20, "cost": 3, "cost_from_recipe": True})
    assert m["cost"] == 3 and m["cost_from_recipe"] is False
    # PUT product with changed recipe
    r = s.put(f"{BASE_URL}/api/products/{p['id']}", json={**p, "cost": 1, "recipe": [{"inventory_id": a["id"], "amount": 0.2}]})
    assert r.status_code == 200 and r.json()["cost"] == 80 and r.json()["cost_from_recipe"] is True
    # PUT manual product keeps manual
    r = s.put(f"{BASE_URL}/api/products/{m['id']}", json={**m, "cost": 4})
    assert r.json()["cost"] == 4 and r.json()["cost_from_recipe"] is False
    # restore 2-ingredient recipe
    s.put(f"{BASE_URL}/api/products/{p['id']}", json={**p, "recipe": [{"inventory_id": a["id"], "amount": 0.15}, {"inventory_id": b["id"], "amount": 1}]})
    # ingredient unit_cost change
    cur = next(i for i in s.get(f"{BASE_URL}/api/inventory").json() if i["id"] == a["id"])
    assert s.put(f"{BASE_URL}/api/inventory/{a['id']}", json={**cur, "unit_cost": 500}).status_code == 200
    assert get_product(s, p["id"])["cost"] == 80  # 0.15*500+5
    assert get_product(s, m["id"])["cost"] == 4
    # sale uses product cost -> report profit
    prod = get_product(s, p["id"])
    sale = create(s, "sales", {"product_id": p["id"], "product_name": p["name"], "quantity": 2, "unit_price": 200, "unit_cost": prod["cost"], "amount": 400})
    assert sale["unit_cost"] == 80
    rep = s.get(f"{BASE_URL}/api/reports", params={"period": "daily"}).json()
    row = next(x for x in rep["top_products"] if x["product_name"] == p["name"])
    assert row["cost"] == 160 and row["profit"] == 240
    # delete ingredient -> recompute
    assert s.delete(f"{BASE_URL}/api/inventory/{b['id']}").status_code == 200
    CREATED.remove(("inventory", b["id"]))
    assert get_product(s, p["id"])["cost"] == 75


# Backend does not derive unit_cost from product if client omits it (informational)
def test_sale_without_unit_cost(s):
    a = create(s, "inventory", {"name": f"TEST_Peynir_{SUFFIX}", "quantity": 10, "unit": "kg", "minimum": 1, "unit_cost": 300})
    p = create(s, "products", {"name": f"TEST_Tost_{SUFFIX}", "price": 100, "recipe": [{"inventory_id": a["id"], "amount": 0.1}]})
    sale = create(s, "sales", {"product_id": p["id"], "product_name": p["name"], "quantity": 1, "unit_price": 100, "amount": 100})
    print("unit_cost when omitted:", sale["unit_cost"])
    assert sale["unit_cost"] in (0, 30)
