import os

import requests


BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")


def test_products_reports_and_reconciliation_endpoints():
    client = requests.Session()
    product = client.post(
        f"{BASE_URL}/api/products",
        json={"name": "TEST_Rapor Ürünü", "category": "TEST", "price": 100, "cost": 35},
        timeout=15,
    )
    assert product.status_code == 200
    product_id = product.json()["id"]
    try:
        listed = client.get(f"{BASE_URL}/api/products", timeout=15)
        assert listed.status_code == 200
        assert any(item["id"] == product_id for item in listed.json())

        for period in ("daily", "weekly", "monthly"):
            report = client.get(f"{BASE_URL}/api/reports", params={"period": period}, timeout=15)
            assert report.status_code == 200
            assert report.json()["period"] == period
            assert isinstance(report.json()["top_products"], list)

        reconciliation = client.get(f"{BASE_URL}/api/cash/reconciliation", timeout=15)
        assert reconciliation.status_code == 200
        body = reconciliation.json()
        for key in ("opening", "sales", "expenses", "expected_closing", "actual_closing", "difference"):
            assert key in body
    finally:
        deleted = client.delete(f"{BASE_URL}/api/products/{product_id}", timeout=15)
        assert deleted.status_code == 200


def test_reports_reject_invalid_period():
    response = requests.get(f"{BASE_URL}/api/reports", params={"period": "yearly"}, timeout=15)
    assert response.status_code == 422