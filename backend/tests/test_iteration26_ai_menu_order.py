# Iteration 26: AI assistant (admin /api/ai/chat SSE + history + PIN/role scoping), QR menu chat (public, rate limit),
# manual menu ordering (/api/menu-order -> /api/public/menu order).
# Run with: pytest tests/test_iteration26_ai_menu_order.py -n 0 -v -s   (ordered, shared state; ~6 real LLM calls + 15 aborted)
import json
import os
import sys
import uuid

import pytest
import requests

from conftest import get_token, ADMIN_EMAIL, MEMBER_EMAIL

sys.path.insert(0, "/app/backend")
BASE = open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split()[0].rstrip("/") + "/api"
FL, TS = "florya-tasfirin", "test-sube"
S = {"products": []}


def adm(rid=FL):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {get_token(ADMIN_EMAIL)[1]}", "X-Restaurant": rid})
    return s


def mgr():
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {get_token(MEMBER_EMAIL)[1]}", "X-Restaurant": TS})
    return s


def sse(resp):
    """Return (text, events) from an SSE response."""
    events = []
    for line in resp.iter_lines(decode_unicode=True):
        if line and line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return "".join(e.get("delta", "") for e in events), events


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    s = adm()
    for pid in S["products"]:
        print("delete product", pid, s.delete(f"{BASE}/products/{pid}").status_code)
    # restore original menu order state (no menu_order doc, adana without sort_order)
    import pymongo
    env = dict(l.split("=", 1) for l in open("/app/backend/.env").read().splitlines() if "=" in l)
    c = pymongo.MongoClient(env["MONGO_URL"].strip('"'))[env["DB_NAME"].strip('"')]
    c.settings.delete_one({"id": "menu_order"})
    c.products.update_one({"name": "adana"}, {"$unset": {"sort_order": ""}})
    print("archive test-sube", adm().post(f"{BASE}/restaurants/manage/{TS}/archive").status_code)


# ---------- admin AI chat: auth & validation ----------
def test_ai_chat_requires_auth():
    r = requests.post(f"{BASE}/ai/chat", json={"session_id": "x" * 12, "message": "hi"}, headers={"X-No-Auth": "1"})
    assert r.status_code in (401, 403), r.text
    r = requests.get(f"{BASE}/ai/history", params={"session_id": "x" * 12}, headers={"X-No-Auth": "1"})
    assert r.status_code in (401, 403)


def test_ai_chat_validation():
    s = adm()
    assert s.post(f"{BASE}/ai/chat", json={"session_id": "short", "message": "hi"}).status_code == 422
    assert s.post(f"{BASE}/ai/chat", json={"session_id": "x" * 12, "message": ""}).status_code == 422
    assert s.post(f"{BASE}/ai/chat", json={"session_id": "x" * 12, "message": "a" * 1001}).status_code == 422


def test_ai_chat_pin_locked_423():
    assert adm().post(f"{BASE}/restaurants/manage/{TS}/restore").status_code == 200
    r = adm(TS).post(f"{BASE}/ai/chat", json={"session_id": "x" * 12, "message": "hi"})
    assert r.status_code == 423, r.text
    r = mgr().post(f"{BASE}/ai/chat", json={"session_id": "x" * 12, "message": "hi"})
    assert r.status_code == 423, r.text


# ---------- admin AI chat: stream + memory + history ----------
def test_ai_chat_stream_and_memory():
    sid = "TEST_" + uuid.uuid4().hex[:20]
    S["sid"] = sid
    r = adm().post(f"{BASE}/ai/chat", json={"session_id": sid, "message": "Bu ay kârım ne durumda? Kısa cevap ver."}, stream=True, timeout=120)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    text, ev = sse(r)
    print("ANSWER1:", text[:300])
    assert ev[-1] == {"done": True}, ev[-3:]
    assert len([e for e in ev if "delta" in e]) > 1 and len(text) > 10
    r = adm().post(f"{BASE}/ai/chat", json={"session_id": sid, "message": "az önce ne sordum?"}, stream=True, timeout=120)
    text2, ev2 = sse(r)
    print("ANSWER2:", text2[:300])
    assert ev2[-1] == {"done": True}
    assert any(w in text2.lower() for w in ("kâr", "kar")), text2


def test_ai_history_persisted_and_owner_scoped():
    h = adm().get(f"{BASE}/ai/history", params={"session_id": S["sid"]}).json()
    assert [m["role"] for m in h] == ["user", "assistant", "user", "assistant"]
    assert h[0]["content"].startswith("Bu ay kârım") and h[2]["content"] == "az önce ne sordum?"
    assert all(set(m) == {"role", "content"} for m in h)
    # another user cannot read this session
    m = mgr()
    key = m.post(f"{BASE}/restaurants/unlock", json={"pins": {TS: "5678"}}).json()["token"]
    m.headers["X-Restaurant-Key"] = key
    S["mkey"] = key
    assert m.get(f"{BASE}/ai/history", params={"session_id": S["sid"]}).json() == []


def test_manager_chat_scoped_to_own_restaurant():
    m = mgr()
    m.headers["X-Restaurant-Key"] = S["mkey"]
    m.headers["X-Restaurant"] = FL  # should be ignored for managers
    sid = "TEST_" + uuid.uuid4().hex[:20]
    r = m.post(f"{BASE}/ai/chat", json={"session_id": sid, "message": "Seçili restoranın adı ne? Sadece adı yaz."}, stream=True, timeout=120)
    assert r.status_code == 200, r.text
    text, ev = sse(r)
    print("MANAGER:", text)
    assert ev[-1] == {"done": True}
    assert "test" in text.lower() and "florya" not in text.lower()


# ---------- public menu chat ----------
def test_menu_chat_public_answers_from_menu():
    sid = "TEST_" + uuid.uuid4().hex[:20]
    r = requests.post(f"{BASE}/public/menu-chat", json={"session_id": sid, "message": "Adana kaç lira?"}, headers={"X-No-Auth": "1"}, stream=True, timeout=120)
    assert r.status_code == 200, r.text
    text, ev = sse(r)
    print("MENU:", text)
    assert ev[-1] == {"done": True}
    assert "530" in text


def test_rate_limit_unit():
    import ai
    k = "TEST_" + uuid.uuid4().hex
    assert [ai.rate_limited(k, 15, 600) for _ in range(16)] == [False] * 15 + [True]


def test_menu_chat_rate_limit_live():
    # unique spoofed client IP (first X-Forwarded-For entry is used as key); streams closed immediately
    ip = f"10.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}"
    codes = []
    for i in range(16):
        r = requests.post(f"{BASE}/public/menu-chat", json={"session_id": "TEST_rl_" + uuid.uuid4().hex[:10], "message": "a"},
                          headers={"X-No-Auth": "1", "X-Forwarded-For": ip}, stream=True, timeout=60)
        codes.append(r.status_code)
        r.close()
    print("RL codes", codes)
    S["rl_codes"] = codes
    assert 429 in codes, codes
    assert codes[-1] == 429


# ---------- menu ordering ----------
def test_create_test_products():
    s = adm()
    for name, cat in (("TEST_A1", "TEST_CatA"), ("TEST_A2", "TEST_CatA"), ("TEST_B1", "TEST_CatB"), ("TEST_B2", "TEST_CatB")):
        r = s.post(f"{BASE}/products", json={"name": name, "price": 10, "category": cat, "active": True})
        assert r.status_code in (200, 201), r.text
        S["products"].append(r.json()["id"])
    cats = s.get(f"{BASE}/menu-order").json()
    names = [c["category"] for c in cats]
    assert {"Kebap", "TEST_CatA", "TEST_CatB"} <= set(names), names
    S["order"] = cats


def test_save_order_reflected_in_public_menu():
    cats = {c["category"]: c for c in S["order"]}
    new_cats = ["TEST_CatB", "Kebap", "TEST_CatA"]
    prod_ids = []
    for c in new_cats:
        prod_ids += [i["id"] for i in reversed(cats[c]["items"])]
    r = adm().put(f"{BASE}/menu-order", json={"categories": new_cats, "products": prod_ids})
    assert r.status_code == 200, r.text
    pub = requests.get(f"{BASE}/public/menu", headers={"X-No-Auth": "1"}).json()["categories"]
    assert [c["category"] for c in pub][:3] == new_cats
    by = {c["category"]: [i["name"] for i in c["items"]] for c in pub}
    assert by["TEST_CatB"] == ["TEST_B2", "TEST_B1"] and by["TEST_CatA"] == ["TEST_A2", "TEST_A1"]
    assert "id" not in pub[0]["items"][0]
    got = adm().get(f"{BASE}/menu-order").json()
    assert [c["category"] for c in got][:3] == new_cats


def test_menu_order_requires_auth_and_validation():
    assert requests.get(f"{BASE}/menu-order", headers={"X-No-Auth": "1"}).status_code in (401, 403)
    assert requests.put(f"{BASE}/menu-order", json={"categories": [], "products": []}, headers={"X-No-Auth": "1"}).status_code in (401, 403)
    assert adm().put(f"{BASE}/menu-order", json={"categories": "x"}).status_code == 422


def test_menu_order_all_mode():
    r = adm("all").put(f"{BASE}/menu-order", json={"categories": ["Kebap"], "products": []})
    print("ALL MODE PUT", r.status_code, r.text)
    S["all_mode"] = r.status_code
