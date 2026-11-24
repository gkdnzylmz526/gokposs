# Iteration 23: product photo upload (object storage) + public QR menu photo_url/description.
# Ordered shared state; run with -n 0. Creates TEST_ product, deletes it (and its photo) at the end.
import io
import struct
import zlib

import pytest
import requests
from pymongo import MongoClient

from conftest import get_token, ADMIN_EMAIL, MEMBER_EMAIL

BASE = open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split()[0].rstrip("/") + "/api"
ENV = dict(l.strip().split("=", 1) for l in open("/app/backend/.env") if "=" in l)
MDB = MongoClient(ENV["MONGO_URL"].strip('"'))[ENV["DB_NAME"].strip('"')]
STATE = {}


def tiny_png(color=(255, 0, 0)):
    raw = b"\x00" + bytes(color)
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def adm():
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {get_token(ADMIN_EMAIL)[1]}"})
    return s


@pytest.fixture(scope="module", autouse=True)
def product():
    r = adm().post(f"{BASE}/products", json={"name": "TEST_Foto Ürün", "category": "TEST_Kat", "price": 99, "description": "TEST_açıklama"})
    assert r.status_code == 200, r.text
    STATE["pid"] = r.json()["id"]
    yield
    adm().delete(f"{BASE}/products/{STATE['pid']}/photo")
    adm().delete(f"{BASE}/products/{STATE['pid']}")


def test_description_saved_and_max_len():
    p = adm().get(f"{BASE}/products").json()
    me = next(x for x in p if x["id"] == STATE["pid"])
    assert me["description"] == "TEST_açıklama" and me.get("photo") == {}
    r = adm().put(f"{BASE}/products/{STATE['pid']}", json={"name": "TEST_Foto Ürün", "category": "TEST_Kat", "price": 99, "description": "x" * 201})
    assert r.status_code == 422


def test_public_menu_no_photo():
    r = requests.get(f"{BASE}/public/menu", headers={"X-No-Auth": "1"})
    assert r.status_code == 200
    it = next(i for c in r.json()["categories"] for i in c["items"] if i["name"] == "TEST_Foto Ürün")
    assert it["photo_url"] == "" and it["description"] == "TEST_açıklama"


def test_upload_bad_type_422():
    r = adm().post(f"{BASE}/products/{STATE['pid']}/photo", files={"file": ("a.gif", b"GIF89a", "image/gif")})
    assert r.status_code == 422
    r = adm().post(f"{BASE}/products/{STATE['pid']}/photo", files={"file": ("a.pdf", b"%PDF", "application/pdf")})
    assert r.status_code == 422
    r = adm().post(f"{BASE}/products/{STATE['pid']}/photo", files={"file": ("a.jpg", b"", "image/jpeg")})
    assert r.status_code == 422


def test_upload_too_big_422():
    r = adm().post(f"{BASE}/products/{STATE['pid']}/photo", files={"file": ("big.jpg", b"\xff" * (5 * 1024 * 1024 + 1), "image/jpeg")})
    assert r.status_code == 422


def test_upload_unknown_product_404():
    r = adm().post(f"{BASE}/products/nope-123/photo", files={"file": ("a.png", tiny_png(), "image/png")})
    assert r.status_code == 404


def test_member_cannot_upload():
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {get_token(MEMBER_EMAIL)[1]}"})
    r = s.post(f"{BASE}/products/{STATE['pid']}/photo", files={"file": ("a.png", tiny_png(), "image/png")})
    assert r.status_code in (401, 403)


def test_no_auth_cannot_upload():
    r = requests.post(f"{BASE}/products/{STATE['pid']}/photo", files={"file": ("a.png", tiny_png(), "image/png")}, headers={"X-No-Auth": "1"})
    assert r.status_code in (401, 403)


def test_upload_png_ok():
    data = tiny_png()
    r = adm().post(f"{BASE}/products/{STATE['pid']}/photo", files={"file": ("a.PNG", data, "image/png")})
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["content_type"] == "image/png" and m["size"] == len(data) and m["filename"] == "a.PNG" and isinstance(m["id"], str)
    STATE["f1"], STATE["d1"] = m["id"], data
    me = next(x for x in adm().get(f"{BASE}/products").json() if x["id"] == STATE["pid"])
    assert me["photo"]["id"] == m["id"]


def test_public_photo_bytes_no_auth():
    r = requests.get(f"{BASE}/public/photos/{STATE['f1']}", headers={"X-No-Auth": "1"})
    assert r.status_code == 200
    assert r.content == STATE["d1"] and r.headers["content-type"].startswith("image/png")


def test_public_menu_has_photo_url():
    it = next(i for c in requests.get(f"{BASE}/public/menu", headers={"X-No-Auth": "1"}).json()["categories"] for i in c["items"] if i["name"] == "TEST_Foto Ürün")
    assert it["photo_url"] == f"/api/public/photos/{STATE['f1']}"


def test_edit_preserves_photo():
    r = adm().put(f"{BASE}/products/{STATE['pid']}", json={"name": "TEST_Foto Ürün", "category": "TEST_Kat", "price": 120, "description": "TEST_yeni", "photo": {}})
    assert r.status_code == 200, r.text
    assert r.json()["photo"]["id"] == STATE["f1"]
    me = next(x for x in adm().get(f"{BASE}/products").json() if x["id"] == STATE["pid"])
    assert me["photo"]["id"] == STATE["f1"] and me["description"] == "TEST_yeni" and me["price"] == 120


def test_replace_marks_old_deleted():
    r = adm().post(f"{BASE}/products/{STATE['pid']}/photo", files={"file": ("b.webp", b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp")})
    assert r.status_code == 200, r.text
    STATE["f2"] = r.json()["id"]
    assert r.json()["content_type"] == "image/webp"
    assert MDB.files.find_one({"id": STATE["f1"]})["is_deleted"] is True
    assert requests.get(f"{BASE}/public/photos/{STATE['f1']}", headers={"X-No-Auth": "1"}).status_code == 404
    assert requests.get(f"{BASE}/public/photos/{STATE['f2']}", headers={"X-No-Auth": "1"}).status_code == 200


def test_invoice_file_not_public():
    f = MDB.files.find_one({"invoice_id": {"$exists": True}, "is_deleted": False}, {"_id": 0, "id": 1})
    if not f:
        pytest.skip("no invoice file")
    assert requests.get(f"{BASE}/public/photos/{f['id']}", headers={"X-No-Auth": "1"}).status_code == 404


def test_fresh_invoice_file_not_public():
    s = adm()
    s.headers["X-Restaurant"] = "florya-tasfirin"
    inv = s.post(f"{BASE}/invoices", json={"supplier": "TEST_Tedarik", "date": "2026-01-10", "amount": 10})
    assert inv.status_code == 200, inv.text
    iid = inv.json()["id"]
    try:
        f = s.post(f"{BASE}/invoices/{iid}/files", files={"file": ("t.png", tiny_png(), "image/png")})
        assert f.status_code == 200, f.text
        fid = f.json()["id"]
        assert s.get(f"{BASE}/files/{fid}").status_code == 200
        assert requests.get(f"{BASE}/public/photos/{fid}", headers={"X-No-Auth": "1"}).status_code == 404
        s.delete(f"{BASE}/invoices/{iid}/files/{fid}")
    finally:
        s.delete(f"{BASE}/invoices/{iid}")


def test_product_photo_not_via_files_endpoint():
    assert adm().get(f"{BASE}/files/{STATE['f2']}").status_code == 404


def test_delete_photo():
    r = adm().delete(f"{BASE}/products/{STATE['pid']}/photo")
    assert r.status_code == 200
    me = next(x for x in adm().get(f"{BASE}/products").json() if x["id"] == STATE["pid"])
    assert me["photo"] == {}
    assert requests.get(f"{BASE}/public/photos/{STATE['f2']}", headers={"X-No-Auth": "1"}).status_code == 404
    it = next(i for c in requests.get(f"{BASE}/public/menu", headers={"X-No-Auth": "1"}).json()["categories"] for i in c["items"] if i["name"] == "TEST_Foto Ürün")
    assert it["photo_url"] == ""
