# Iteration 25 post-UI checks + cleanup: verify approved PIN via UI (4321), then restore test-sube to PIN 5678, drop UI-uploaded cover, archive.
import requests
from conftest import get_token, ADMIN_EMAIL, MEMBER_EMAIL

BASE = open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split()[0].rstrip("/") + "/api"
A = {"Authorization": f"Bearer {get_token(ADMIN_EMAIL)[1]}", "X-Restaurant": "florya-tasfirin"}
M = {"Authorization": f"Bearer {get_token(MEMBER_EMAIL)[1]}", "X-Restaurant": "test-sube"}
print("mgr unlock 4321:", requests.post(f"{BASE}/restaurants/unlock", json={"pins": {"test-sube": "4321"}}, headers=M).status_code)
print("mgr unlock 5678 (old):", requests.post(f"{BASE}/restaurants/unlock", json={"pins": {"test-sube": "5678"}}, headers=M).status_code)
print("pending:", requests.get(f"{BASE}/restaurants/manage/pin-requests", headers=A).json())
print("remove cover:", requests.delete(f"{BASE}/restaurants/manage/test-sube/image/cover", headers=A).status_code)
print("pin 5678:", requests.patch(f"{BASE}/restaurants/manage/test-sube", json={"pin": "5678"}, headers=A).status_code)
print("mgr unlock 5678:", requests.post(f"{BASE}/restaurants/unlock", json={"pins": {"test-sube": "5678"}}, headers=M).status_code)
rows = {r["id"]: r for r in requests.get(f"{BASE}/restaurants/manage", headers=A).json()}
for rid in ("florya-tasfirin", "etiler-marmaris", "durumtir"):
    print(rid, "logo", repr(rows[rid]["logo_id"]), "cover", repr(rows[rid]["cover_id"]), "archived", rows[rid]["archived"])
print("test-sube", rows["test-sube"]["logo_id"], repr(rows["test-sube"]["cover_id"]))
print("TEST_ active:", [r["id"] for r in rows.values() if r["name"].startswith("TEST_") and not r["archived"]])
print("archive test-sube:", requests.post(f"{BASE}/restaurants/manage/test-sube/archive", headers=A).status_code)
