# Iteration 24: restaurant management (add/edit/archive/restore), per-restaurant PIN gate (423/401/token), manager role scoping by restaurant email.
# Run with: pytest tests/test_iteration24_restaurant_admin_pin.py -n 0 -v   (ordered, shared state)
import requests
import pytest

from conftest import get_token, ADMIN_EMAIL, MEMBER_EMAIL

BASE = open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split()[0].rstrip("/") + "/api"
FL, ET, DU, TS = "florya-tasfirin", "etiler-marmaris", "durumtir", "test-sube"
TS_PIN = "5678"
S = {}
CREATED = []  # restaurant ids created by this module -> archived at teardown


def adm(rid, key=None):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {get_token(ADMIN_EMAIL)[1]}", "X-Restaurant": rid})
    if key:
        s.headers["X-Restaurant-Key"] = key
    return s


def mgr(rid=TS, key=None):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {get_token(MEMBER_EMAIL)[1]}", "X-Restaurant": rid})
    if key:
        s.headers["X-Restaurant-Key"] = key
    return s


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    for rid in CREATED:
        r = adm(FL).post(f"{BASE}/restaurants/manage/{rid}/archive")
        print("cleanup archive", rid, r.status_code)


# --- registry ---
def test_manage_list_contains_test_sube():
    r = adm(FL).get(f"{BASE}/restaurants/manage")
    assert r.status_code == 200, r.text
    rows = {x["id"]: x for x in r.json()}
    assert {FL, ET, DU, TS} <= set(rows)
    assert rows[TS]["has_pin"] is True and rows[TS]["email"] == MEMBER_EMAIL
    assert all("pin_hash" not in x for x in r.json())
    for rid in (FL, ET, DU):
        assert rows[rid]["has_pin"] is False and rows[rid]["archived"] is False


def test_me_admin_lists_restaurants_with_has_pin():
    d = adm(FL).get(f"{BASE}/me").json()
    ids = {x["id"]: x for x in d["restaurants"]}
    assert d["role"] == "admin" and {FL, ET, DU, TS} <= set(ids) and ids[TS]["has_pin"] is True


# --- PIN gate (admin) ---
def test_pinned_restaurant_requires_key():
    r = adm(TS).get(f"{BASE}/dashboard")
    assert r.status_code == 423 and "şifre" in r.json()["detail"].lower()
    assert adm(TS, key="garbage").get(f"{BASE}/dashboard").status_code == 423


def test_wrong_pin_401_and_correct_pin_token():
    w = adm(TS).post(f"{BASE}/restaurants/unlock", json={"pins": {TS: "0000"}})
    assert w.status_code == 401 and "hatalı" in w.json()["detail"]
    ok = adm(TS).post(f"{BASE}/restaurants/unlock", json={"pins": {TS: TS_PIN}})
    assert ok.status_code == 200, ok.text
    S["ts_key"] = ok.json()["token"]
    d = adm(TS, S["ts_key"]).get(f"{BASE}/dashboard")
    assert d.status_code == 200 and d.json()["restaurant_id"] == TS


def test_unpinned_restaurants_open_without_key():
    for rid in (FL, ET, DU):
        assert adm(rid).get(f"{BASE}/dashboard").status_code == 200, rid


def test_all_mode_needs_all_pins():
    assert adm("all").get(f"{BASE}/dashboard").status_code == 423
    # token only valid for currently pinned set (only test-sube is pinned at this point)
    assert adm("all", S["ts_key"]).get(f"{BASE}/dashboard").status_code == 200


def test_summary_hides_locked_restaurants():
    no_key = {r["id"] for r in adm(FL).get(f"{BASE}/restaurants/summary").json()}
    assert TS not in no_key and FL in no_key
    with_key = {r["id"] for r in adm(FL, S["ts_key"]).get(f"{BASE}/restaurants/summary").json()}
    assert TS in with_key


# --- create / validation ---
def test_create_validation():
    s = adm(FL)
    assert s.post(f"{BASE}/restaurants/manage", json={"name": "TEST_x", "pin": "12"}).status_code == 422
    assert s.post(f"{BASE}/restaurants/manage", json={"name": "TEST_x", "pin": "abcd"}).status_code == 422
    assert s.post(f"{BASE}/restaurants/manage", json={"name": "TEST_x", "email": "not-an-email"}).status_code == 422
    assert s.post(f"{BASE}/restaurants/manage", json={"name": ""}).status_code == 422
    dup = s.post(f"{BASE}/restaurants/manage", json={"name": "TEST_x", "email": MEMBER_EMAIL.upper()})
    assert dup.status_code == 409


def test_create_restaurant_with_pin():
    r = adm(FL).post(f"{BASE}/restaurants/manage", json={"name": "TEST_Bakırköy Şube", "email": "", "pin": "1234"})
    assert r.status_code == 200, r.text
    d = r.json()
    CREATED.append(d["id"])
    S["new"] = d["id"]
    assert d["id"].startswith("test-bakirkoy-sube") and d["has_pin"] is True and d["archived"] is False
    me = {x["id"]: x for x in adm(FL).get(f"{BASE}/me").json()["restaurants"]}
    assert S["new"] in me and me[S["new"]]["has_pin"] is True
    # the old all-mode token no longer covers the new pinned restaurant
    assert adm("all", S["ts_key"]).get(f"{BASE}/dashboard").status_code == 423
    assert adm(S["new"], S["ts_key"]).get(f"{BASE}/dashboard").status_code == 423
    k = adm("all").post(f"{BASE}/restaurants/unlock", json={"pins": {TS: TS_PIN, S["new"]: "1234"}})
    assert k.status_code == 200
    assert adm("all", k.json()["token"]).get(f"{BASE}/dashboard").status_code == 200
    S["new_key"] = adm(S["new"]).post(f"{BASE}/restaurants/unlock", json={"pins": {S["new"]: "1234"}}).json()["token"]
    assert adm(S["new"], S["new_key"]).get(f"{BASE}/dashboard").status_code == 200


def test_duplicate_name_gets_unique_slug():
    r = adm(FL).post(f"{BASE}/restaurants/manage", json={"name": "TEST_Bakırköy Şube"})
    assert r.status_code == 200, r.text
    CREATED.append(r.json()["id"])
    assert r.json()["id"] != S["new"] and r.json()["has_pin"] is False
    # admin in "Tüm restoranlar" mode can also manage restaurants
    a = adm("all").post(f"{BASE}/restaurants/manage/{r.json()['id']}/archive")
    assert a.status_code == 200, a.text


# --- edit ---
def test_edit_name_and_pin_invalidates_token():
    r = adm(FL).patch(f"{BASE}/restaurants/manage/{S['new']}", json={"name": "TEST_Bakırköy 2", "pin": "4321"})
    assert r.status_code == 200 and r.json()["name"] == "TEST_Bakırköy 2"
    assert adm(S["new"], S["new_key"]).get(f"{BASE}/dashboard").status_code == 423
    k = adm(S["new"]).post(f"{BASE}/restaurants/unlock", json={"pins": {S["new"]: "4321"}})
    assert k.status_code == 200
    assert adm(S["new"], k.json()["token"]).get(f"{BASE}/dashboard").status_code == 200
    rows = {x["id"]: x for x in adm(FL).get(f"{BASE}/restaurants/manage").json()}
    assert rows[S["new"]]["name"] == "TEST_Bakırköy 2"


def test_edit_clear_pin():
    r = adm(FL).patch(f"{BASE}/restaurants/manage/{S['new']}", json={"pin": ""})
    assert r.status_code == 200 and r.json()["has_pin"] is False
    assert adm(S["new"]).get(f"{BASE}/dashboard").status_code == 200
    assert adm(FL).patch(f"{BASE}/restaurants/manage/nope", json={"name": "x"}).status_code == 404


# --- archive / restore ---
def test_archive_and_restore():
    s = adm(FL)
    a = s.post(f"{BASE}/restaurants/manage/{S['new']}/archive")
    assert a.status_code == 200 and a.json()["archived"] is True
    assert S["new"] not in {x["id"] for x in s.get(f"{BASE}/me").json()["restaurants"]}
    assert adm(S["new"]).get(f"{BASE}/dashboard").status_code == 400
    rows = {x["id"]: x for x in s.get(f"{BASE}/restaurants/manage").json()}
    assert rows[S["new"]]["archived"] is True
    assert s.post(f"{BASE}/restaurants/manage/{S['new']}/archive").status_code == 404  # already archived
    assert s.post(f"{BASE}/restaurants/unlock", json={"pins": {S["new"]: "1234"}}).status_code == 403
    rs = s.post(f"{BASE}/restaurants/manage/{S['new']}/restore")
    assert rs.status_code == 200 and rs.json()["archived"] is False
    assert S["new"] in {x["id"] for x in s.get(f"{BASE}/me").json()["restaurants"]}
    assert adm(S["new"]).get(f"{BASE}/dashboard").status_code == 200
    assert s.post(f"{BASE}/restaurants/manage/nope/restore").status_code == 404


# --- manager ---
def test_manager_me_scoped():
    d = mgr(FL).get(f"{BASE}/me").json()
    assert d["role"] == "manager" and d["restaurant_id"] == TS
    assert [x["id"] for x in d["restaurants"]] == [TS]


def test_manager_forbidden_admin_routes():
    m = mgr()
    for path in ("users", "restaurants/manage", "audit-logs", "settings"):
        assert m.get(f"{BASE}/{path}").status_code == 403, path
    assert m.post(f"{BASE}/restaurants/manage", json={"name": "TEST_hack"}).status_code == 403


def test_manager_pin_gate_and_scoping():
    m = mgr(FL)  # header pointing to florya must be ignored
    assert m.get(f"{BASE}/dashboard").status_code == 423
    assert m.post(f"{BASE}/restaurants/unlock", json={"pins": {FL: "0000"}}).status_code == 403
    assert m.post(f"{BASE}/restaurants/unlock", json={"pins": {ET: ""}}).status_code == 403
    k = m.post(f"{BASE}/restaurants/unlock", json={"pins": {TS: TS_PIN}})
    assert k.status_code == 200
    d = mgr(FL, k.json()["token"]).get(f"{BASE}/dashboard")
    assert d.status_code == 200 and d.json()["restaurant_id"] == TS
    assert mgr(FL, k.json()["token"]).get(f"{BASE}/restaurants/summary").json() == []
    # admin's token cannot be reused by manager (uid bound)
    assert mgr(TS, S["ts_key"]).get(f"{BASE}/dashboard").status_code == 423


def test_users_roles_include_manager():
    d = adm(FL).get(f"{BASE}/users").json()
    assert "manager" in d["roles"]
    member = [u for u in d["users"] if u.get("email") == MEMBER_EMAIL]
    assert member and member[0]["role"] == "manager" and member[0]["restaurant_id"] == TS


def test_test_sube_state_intact():
    rows = {x["id"]: x for x in adm(FL).get(f"{BASE}/restaurants/manage").json()}
    assert rows[TS]["has_pin"] and rows[TS]["email"] == MEMBER_EMAIL and not rows[TS]["archived"]


def test_admin_global_pages_open_while_restaurant_locked():
    # Kullanıcılar page is reachable while the selected restaurant is still locked (PIN-free admin routes)
    s = adm(TS)
    for path in ("users", "audit-logs", "settings", "restaurants/manage"):
        assert s.get(f"{BASE}/{path}").status_code == 200, path
    assert s.get(f"{BASE}/dashboard").status_code == 423
