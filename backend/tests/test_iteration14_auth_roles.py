# Iteration 14: Clerk auth guard (401/403/200), /api/me, users list & role changes, public/cron exemptions.
import os
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split()[0].rstrip("/")
API = f"{BASE_URL}/api"
NOAUTH = {"X-No-Auth": "1"}


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


# --- Guard: no token / bad token / member / admin
class TestGuard:
    @pytest.mark.parametrize("path", ["/dashboard", "/reports", "/sales", "/staff", "/users", "/payroll", "/email/status", "/order-list", "/"])
    def test_no_token_401(self, path):
        r = requests.get(f"{API}{path}", headers=NOAUTH)
        assert r.status_code == 401, (path, r.status_code, r.text)

    def test_post_no_token_401(self):
        r = requests.post(f"{API}/sales", json={"product_name": "TEST_x"}, headers=NOAUTH)
        assert r.status_code == 401

    def test_bad_token_401(self):
        r = requests.get(f"{API}/dashboard", headers=bearer("garbage.token.value"))
        assert r.status_code == 401

    def test_me_no_token_401(self):
        assert requests.get(f"{API}/me", headers=NOAUTH).status_code == 401

    @pytest.mark.parametrize("path", ["/dashboard", "/users", "/sales", "/reports"])
    def test_member_403(self, member_auth, path):
        r = requests.get(f"{API}{path}", headers=bearer(member_auth[1]))
        assert r.status_code == 403, (path, r.status_code)
        assert "yetki" in r.json()["detail"].lower()

    def test_member_write_403(self, member_auth):
        r = requests.post(f"{API}/suppliers", json={"name": "TEST_nope"}, headers=bearer(member_auth[1]))
        assert r.status_code == 403

    def test_admin_dashboard_200(self, admin_auth):
        r = requests.get(f"{API}/dashboard", headers=bearer(admin_auth[1]))
        assert r.status_code == 200
        assert "revenue" in r.json()

    def test_me_roles(self, admin_auth, member_auth):
        a = requests.get(f"{API}/me", headers=bearer(admin_auth[1])).json()
        m = requests.get(f"{API}/me", headers=bearer(member_auth[1])).json()
        assert a["role"] == "admin" and a["user_id"] == admin_auth[0] and a["email"].startswith("gokboss-admin")
        assert m["role"] == "member" and m["user_id"] == member_auth[0]


# --- Exempt routes
class TestExempt:
    def test_clerk_config_public(self):
        r = requests.get(f"{API}/clerk/config", headers=NOAUTH)
        assert r.status_code == 200
        d = r.json()
        assert d["enabled"] is True and d["publishable_key"].startswith("pk_")

    def test_public_leave_bad_token_404_not_401(self):
        r = requests.get(f"{API}/public/leave/{'b' * 22}", headers=NOAUTH)
        assert r.status_code == 404

    @pytest.mark.parametrize("path", ["daily-report", "weekly-summary", "monthly-summary"])
    def test_cron_401_without_secret(self, path):
        assert requests.post(f"{API}/cron/{path}", headers=NOAUTH).status_code == 401
        assert requests.post(f"{API}/cron/{path}", headers={"Authorization": "Bearer wrong"}).status_code == 401

    def test_cron_admin_token_still_401(self, admin_auth):
        assert requests.post(f"{API}/cron/monthly-summary", headers=bearer(admin_auth[1])).status_code == 401

    def test_public_leave_valid_token_without_auth(self, admin_auth):
        s = requests.post(f"{API}/staff", json={"name": f"TEST_pub_{uuid.uuid4().hex[:5]}", "hourly_wage": 100}, headers=bearer(admin_auth[1]))
        assert s.status_code == 200, s.text
        staff = s.json()
        try:
            tok = staff.get("request_token")
            assert tok
            r = requests.get(f"{API}/public/leave/{tok}", headers=NOAUTH)
            assert r.status_code == 200
            assert r.json()["staff"]["name"] == staff["name"] if "staff" in r.json() else staff["name"] in r.text
        finally:
            requests.delete(f"{API}/staff/{staff['id']}", headers=bearer(admin_auth[1]))


# --- Users API
class TestUsers:
    def test_list(self, admin_auth):
        d = requests.get(f"{API}/users", headers=bearer(admin_auth[1])).json()
        assert d["roles"] == ["admin", "member"]
        emails = {u["email"]: u["role"] for u in d["users"]}
        assert emails.get("gokboss-admin+clerk_test@example.com") == "admin"
        assert emails.get("gokboss-member+clerk_test@example.com") == "member"
        assert all("_id" not in u for u in d["users"])

    def test_invalid_role_403(self, admin_auth, member_auth):
        r = requests.patch(f"{API}/users/{member_auth[0]}/role", json={"role": "owner"}, headers=bearer(admin_auth[1]))
        assert r.status_code == 403

    def test_unknown_user_404(self, admin_auth):
        r = requests.patch(f"{API}/users/user_doesnotexist/role", json={"role": "admin"}, headers=bearer(admin_auth[1]))
        assert r.status_code == 404

    def test_member_cannot_change_roles(self, member_auth):
        r = requests.patch(f"{API}/users/{member_auth[0]}/role", json={"role": "admin"}, headers=bearer(member_auth[1]))
        assert r.status_code == 403
        assert requests.get(f"{API}/me", headers=bearer(member_auth[1])).json()["role"] == "member"

    def test_promote_and_demote_member(self, admin_auth, member_auth):
        h = bearer(admin_auth[1])
        try:
            r = requests.patch(f"{API}/users/{member_auth[0]}/role", json={"role": "admin"}, headers=h)
            assert r.status_code == 200 and r.json()["role"] == "admin"
            assert requests.get(f"{API}/me", headers=bearer(member_auth[1])).json()["role"] == "admin"
            assert requests.get(f"{API}/dashboard", headers=bearer(member_auth[1])).status_code == 200
        finally:
            r = requests.patch(f"{API}/users/{member_auth[0]}/role", json={"role": "member"}, headers=h)
        assert r.status_code == 200
        assert requests.get(f"{API}/dashboard", headers=bearer(member_auth[1])).status_code == 403

    def test_demote_last_admin_409(self, admin_auth):
        users = requests.get(f"{API}/users", headers=bearer(admin_auth[1])).json()["users"]
        if sum(u["role"] == "admin" for u in users) > 1:
            pytest.skip("More than one admin exists (real owner); cannot test last-admin 409 without touching real accounts")
        r = requests.patch(f"{API}/users/{admin_auth[0]}/role", json={"role": "member"}, headers=bearer(admin_auth[1]))
        assert r.status_code == 409
        assert requests.get(f"{API}/me", headers=bearer(admin_auth[1])).json()["role"] == "admin"
