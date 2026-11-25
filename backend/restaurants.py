import base64
import hashlib
import hmac
import os
import secrets
import time
from typing import Any, Dict, List

from fastapi import HTTPException

from scope import RESTAURANT_IDS, RESTAURANT_NAMES, RESTAURANTS

SEED = [{"id": "florya-tasfirin", "name": "Florya Taşfırın"}, {"id": "etiler-marmaris", "name": "Etiler Marmaris"}, {"id": "durumtir", "name": "Dürümtır"}]
DOCS: Dict[str, Dict[str, Any]] = {}
TOKEN_TTL = 12 * 3600
_fails: Dict[str, List[float]] = {}


def refresh(docs: List[Dict[str, Any]]) -> None:
    """Update the shared in-memory restaurant registry in place (other modules hold references)."""
    DOCS.clear()
    DOCS.update({d["id"]: d for d in docs})
    active = [d for d in docs if not d.get("archived")]
    RESTAURANTS[:] = [{"id": d["id"], "name": d["name"], "has_pin": bool(d.get("pin_hash")), "logo_id": d.get("logo_id", ""), "cover_id": d.get("cover_id", "")} for d in active]
    RESTAURANT_IDS.clear()
    RESTAURANT_IDS.update(d["id"] for d in active)
    RESTAURANT_NAMES.clear()
    RESTAURANT_NAMES.update({d["id"]: d["name"] for d in docs})


def default_rid() -> str:
    return RESTAURANTS[0]["id"] if RESTAURANTS else SEED[0]["id"]


def hash_pin(pin: str) -> str:
    salt = secrets.token_hex(8)
    return f"{salt}${hashlib.pbkdf2_hmac('sha256', pin.encode(), salt.encode(), 120000).hex()}"


def check_pin(pin: str, stored: str) -> bool:
    salt, digest = stored.split("$", 1)
    return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 120000).hex(), digest)


def _key() -> bytes:
    return hashlib.sha256(f"restaurant-pin:{os.environ['CLERK_SECRET_KEY']}".encode()).digest()


def _sig(uid: str, rids: str, exp: int) -> str:
    pins = "|".join(DOCS.get(r, {}).get("pin_hash", "") for r in rids.split(","))
    return hmac.new(_key(), f"{uid}|{rids}|{exp}|{pins}".encode(), hashlib.sha256).hexdigest()


def make_token(uid: str, rids: List[str]) -> str:
    joined, exp = ",".join(sorted(rids)), int(time.time()) + TOKEN_TTL
    return base64.urlsafe_b64encode(f"{joined}|{exp}|{_sig(uid, joined, exp)}".encode()).decode()


def unlocked(uid: str, token: str | None) -> set:
    try:
        joined, exp, sig = base64.urlsafe_b64decode((token or "").encode()).decode().split("|")
        if int(exp) > time.time() and hmac.compare_digest(sig, _sig(uid, joined, int(exp))):
            return set(joined.split(","))
    except Exception:
        pass
    return set()


def require_unlocked(uid: str, rid: str, token: str | None) -> None:
    needed = {r["id"] for r in RESTAURANTS if r["has_pin"]} if rid == "all" else ({rid} if DOCS.get(rid, {}).get("pin_hash") else set())
    if needed - unlocked(uid, token):
        raise HTTPException(status_code=423, detail="Restoran şifresi gerekli")


def throttle(uid: str) -> None:
    now = time.time()
    recent = [t for t in _fails.get(uid, []) if now - t < 300]
    _fails[uid] = recent
    if len(recent) >= 5:
        raise HTTPException(status_code=429, detail="Çok fazla hatalı deneme. 5 dakika sonra tekrar deneyin")


def record_fail(uid: str) -> None:
    _fails.setdefault(uid, []).append(time.time())
