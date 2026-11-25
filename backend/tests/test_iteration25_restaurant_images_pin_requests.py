# Iteration 25: restaurant logo/cover upload + public serving, manager "forgot PIN" requests (create/replace/approve/reject), role guards.
# Run with: pytest tests/test_iteration25_restaurant_images_pin_requests.py -n 0 -v   (ordered, shared state)
# Leaves test-sube with PIN 5678 (archive is done separately at the end of the testing session).
import io
import struct
import zlib

import pytest
import requests

from conftest import get_token, ADMIN_EMAIL, MEMBER_EMAIL

BASE = open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split()[0].rstrip("/") + "/api"
FL, TS = "florya-tasfirin", "test-sube"
S = {}
CREATED = []


def _png(r=255, g=0, b=0):
    raw = b"".join(b"\x00" + bytes([r, g, b]) * 4 for _ in range(4))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def adm(rid=FL):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {get_token(ADMIN_EMAIL)[1]}", "X-Restaurant": rid})
    return s


def mgr():
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {get_token(MEMBER_EMAIL)[1]}", "X-Restaurant": TS})
    return s


def unlock_mgr(pin):
    return mgr().post(f"{BASE}/restaurants/unlock", json={"pins": {TS: pin}})


def pending_for_ts():
    r = adm().get(f"{BASE}/restaurants/manage/pin-requests")
    assert r.status_code == 200, r.text
    return [x for x in r.json() if x["restaurant_id"] == TS]


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    for rid in CREATED:
        print("cleanup archive", rid, adm().post(f"{BASE}/restaurants/manage/{rid}/archive").status_code)
    # ensure final PIN 5678
    print("reset pin", adm().patch(f"{BASE}/restaurants/manage/{TS}", json={"pin": "5678"}).status_code)


# --- precondition ---
def test_test_sube_active_and_current_pin():
    rows = {x["id"]: x for x in adm().get(f"{BASE}/restaurants/manage").json()}
    assert rows[TS]["archived"] is False and rows[TS]["has_pin"] is True
    assert "logo_id" in rows[TS] and "cover_id" in rows[TS]
    # set a known PIN so the flow is deterministic
    assert adm().patch(f"{BASE}/restaurants/manage/{TS}", json={"pin": "2468"}).status_code == 200
    assert unlock_mgr("2468").status_code == 200


# --- pin-request validation & guards ---
def test_pin_request_validation():
    m = mgr()
    for bad in ("12", "abcd", "12a4"):
        r = m.post(f"{BASE}/restaurants/pin-request", json={"restaurant_id": TS, "new_pin": bad})
        assert r.status_code == 422, (bad, r.text)
    assert m.post(f"{BASE}/restaurants/pin-request", json={"restaurant_id": TS, "new_pin": "1234567"}).status_code == 422
    assert m.post(f"{BASE}/restaurants/pin-request", json={"restaurant_id": FL, "new_pin": "1234"}).status_code == 403
    assert m.post(f"{BASE}/restaurants/pin-request", json={"restaurant_id": "nope", "new_pin": "1234"}).status_code == 403


def test_manager_cannot_list_or_decide_or_upload():
    m = mgr()
    assert m.get(f"{BASE}/restaurants/manage/pin-requests").status_code == 403
    assert m.post(f"{BASE}/restaurants/manage/pin-requests/x/approve").status_code == 403
    files = {"file": ("a.png", _png(), "image/png")}
    assert m.post(f"{BASE}/restaurants/manage/{TS}/image/logo", files=files).status_code == 403
    assert m.delete(f"{BASE}/restaurants/manage/{TS}/image/logo").status_code == 403


def test_request_and_replace():
    m = mgr()
    assert m.post(f"{BASE}/restaurants/pin-request", json={"restaurant_id": TS, "new_pin": "1357"}).json() == {"ok": True}
    first = pending_for_ts()
    assert len(first) == 1
    r = m.post(f"{BASE}/restaurants/pin-request", json={"restaurant_id": TS, "new_pin": "9753"})
    assert r.status_code == 200
    rows = pending_for_ts()
    assert len(rows) == 1 and rows[0]["id"] != first[0]["id"]
    row = rows[0]
    assert "pin_hash" not in row and row["user_email"] == MEMBER_EMAIL and row["restaurant_name"] and row["status"] == "pending"
    S["req"] = row["id"]
    # PIN not changed until approved
    assert unlock_mgr("2468").status_code == 200


def test_reject_keeps_pin():
    s = adm()
    assert s.post(f"{BASE}/restaurants/manage/pin-requests/{S['req']}/maybe").status_code == 404
    r = s.post(f"{BASE}/restaurants/manage/pin-requests/{S['req']}/reject")
    assert r.status_code == 200
    assert pending_for_ts() == []
    assert s.post(f"{BASE}/restaurants/manage/pin-requests/{S['req']}/approve").status_code == 404  # already decided
    assert unlock_mgr("2468").status_code == 200


def test_approve_changes_pin():
    old_key = unlock_mgr("2468").json()["token"]
    assert mgr().post(f"{BASE}/restaurants/pin-request", json={"restaurant_id": TS, "new_pin": "5678"}).status_code == 200
    rid = pending_for_ts()[0]["id"]
    assert adm().post(f"{BASE}/restaurants/manage/pin-requests/{rid}/approve").status_code == 200
    assert pending_for_ts() == []
    assert unlock_mgr("5678").status_code == 200
    assert unlock_mgr("2468").status_code == 401
    # old token invalidated by PIN change
    s = mgr(); s.headers["X-Restaurant-Key"] = old_key
    assert s.get(f"{BASE}/dashboard").status_code == 423


def test_pin_request_admin_allowed_no_email():
    # admin may create too (not spec'd as forbidden); record behaviour then reject it
    r = adm().post(f"{BASE}/restaurants/pin-request", json={"restaurant_id": TS, "new_pin": "1111"})
    S["admin_req_status"] = r.status_code
    print("admin pin-request status", r.status_code)
    for row in pending_for_ts():
        adm().post(f"{BASE}/restaurants/manage/pin-requests/{row['id']}/reject")
    assert pending_for_ts() == []


# --- images ---
def test_create_test_restaurant():
    r = adm().post(f"{BASE}/restaurants/manage", json={"name": "TEST_Logo Şube"})
    assert r.status_code == 200, r.text
    S["rid"] = r.json()["id"]
    CREATED.append(S["rid"])
    assert r.json()["logo_id"] == "" and r.json()["cover_id"] == ""


def test_image_validation():
    s, rid = adm(), S["rid"]
    assert s.post(f"{BASE}/restaurants/manage/{rid}/image/logo", files={"file": ("a.gif", b"GIF89a", "image/gif")}).status_code == 422
    assert s.post(f"{BASE}/restaurants/manage/{rid}/image/logo", files={"file": ("a.txt", b"hi", "text/plain")}).status_code == 422
    assert s.post(f"{BASE}/restaurants/manage/{rid}/image/logo", files={"file": ("noext", b"hi", "image/png")}).status_code == 422
    assert s.post(f"{BASE}/restaurants/manage/{rid}/image/logo", files={"file": ("a.png", b"", "image/png")}).status_code == 422
    assert s.post(f"{BASE}/restaurants/manage/{rid}/image/banner", files={"file": ("a.png", _png(), "image/png")}).status_code == 404
    assert s.post(f"{BASE}/restaurants/manage/nope/image/logo", files={"file": ("a.png", _png(), "image/png")}).status_code == 404


def test_upload_logo_and_cover_served_publicly():
    s, rid = adm(), S["rid"]
    data = _png()
    r = s.post(f"{BASE}/restaurants/manage/{rid}/image/logo", files={"file": ("logo.png", data, "image/png")})
    assert r.status_code == 200, r.text
    S["logo"] = r.json()["id"]
    c = s.post(f"{BASE}/restaurants/manage/{rid}/image/cover", files={"file": ("cover.jpg", data, "image/jpeg")})
    assert c.status_code == 200, c.text
    S["cover"] = c.json()["id"]
    p = requests.get(f"{BASE}/public/photos/{S['logo']}", headers={"X-No-Auth": "1"})
    assert p.status_code == 200 and p.headers["content-type"].startswith("image/png") and p.content == data
    pc = requests.get(f"{BASE}/public/photos/{S['cover']}", headers={"X-No-Auth": "1"})
    assert pc.status_code == 200 and pc.headers["content-type"].startswith("image/jpeg")
    rows = {x["id"]: x for x in s.get(f"{BASE}/restaurants/manage").json()}
    assert rows[rid]["logo_id"] == S["logo"] and rows[rid]["cover_id"] == S["cover"]
    me = {x["id"]: x for x in s.get(f"{BASE}/me").json()["restaurants"]}
    assert me[rid].get("logo_id") == S["logo"] and me[rid].get("cover_id") == S["cover"]


def test_replace_logo_retires_old():
    s, rid = adm(), S["rid"]
    r = s.post(f"{BASE}/restaurants/manage/{rid}/image/logo", files={"file": ("logo2.webp", _png(0, 0, 255), "image/webp")})
    assert r.status_code == 200
    assert requests.get(f"{BASE}/public/photos/{S['logo']}", headers={"X-No-Auth": "1"}).status_code == 404
    S["logo"] = r.json()["id"]
    assert requests.get(f"{BASE}/public/photos/{S['logo']}", headers={"X-No-Auth": "1"}).status_code == 200


def test_delete_images():
    s, rid = adm(), S["rid"]
    assert s.delete(f"{BASE}/restaurants/manage/{rid}/image/logo").status_code == 200
    rows = {x["id"]: x for x in s.get(f"{BASE}/restaurants/manage").json()}
    assert rows[rid]["logo_id"] == "" and rows[rid]["cover_id"] == S["cover"]
    assert requests.get(f"{BASE}/public/photos/{S['logo']}", headers={"X-No-Auth": "1"}).status_code == 404
    assert s.delete(f"{BASE}/restaurants/manage/{rid}/image/cover").status_code == 200
    assert s.delete(f"{BASE}/restaurants/manage/{rid}/image/bogus").status_code == 404


def test_manager_me_has_logo():
    me = mgr().get(f"{BASE}/me").json()
    ts = [x for x in me["restaurants"] if x["id"] == TS][0]
    assert "logo_id" in ts and "cover_id" in ts
    print("test-sube logo_id", ts["logo_id"])


def test_public_photo_unknown_404():
    assert requests.get(f"{BASE}/public/photos/does-not-exist", headers={"X-No-Auth": "1"}).status_code == 404
