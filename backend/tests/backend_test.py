import os

import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")


@pytest.fixture
def client():
    return requests.Session()


def test_dashboard_shape(client):
    response = client.get(f"{BASE_URL}/api/dashboard", timeout=15)
    assert response.status_code == 200
    data = response.json()
    for key in ("revenue", "expenses", "profit", "low_stock", "staff_count", "sales", "expenses_list", "inventory", "staff", "cash"):
        assert key in data


@pytest.mark.parametrize("collection,payload,expected", [
    ("sales", {"amount": 123.45, "channel": "TEST_Salon", "note": "TEST satış"}, "amount"),
    ("expenses", {"amount": 23.45, "category": "TEST", "note": "TEST gider"}, "amount"),
    ("inventory", {"name": "TEST_Domates", "quantity": 2, "unit": "kg", "minimum": 5}, "name"),
    ("staff", {"name": "TEST_Personel", "shift": "09:00", "task": "TEST görev"}, "name"),
    ("cash", {"opening": 100, "closing": 150, "note": "TEST kasa"}, "opening"),
])
def test_create_list_delete_collection(client, collection, payload, expected):
    created = client.post(f"{BASE_URL}/api/{collection}", json=payload, timeout=15)
    assert created.status_code == 200
    item = created.json()
    assert item[expected] == payload[expected]
    item_id = item["id"]
    try:
        listed = client.get(f"{BASE_URL}/api/{collection}", timeout=15)
        assert listed.status_code == 200
        assert any(row["id"] == item_id for row in listed.json())
    finally:
        deleted = client.delete(f"{BASE_URL}/api/{collection}/{item_id}", timeout=15)
        assert deleted.status_code == 200