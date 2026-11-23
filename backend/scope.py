from contextvars import ContextVar
from typing import Any, Dict

from fastapi import HTTPException

RESTAURANTS = [{"id": "florya-tasfirin", "name": "Florya Taşfırın"}, {"id": "etiler-marmaris", "name": "Etiler Marmaris"}, {"id": "durumtir", "name": "Dürümtır"}]
RESTAURANT_IDS = {r["id"] for r in RESTAURANTS}
RESTAURANT_NAMES = {r["id"]: r["name"] for r in RESTAURANTS}
DEFAULT_RESTAURANT = RESTAURANTS[0]["id"]
SCOPED = {"sales", "expenses", "inventory", "staff", "cash", "shifts", "leaves", "advances", "orders", "waste", "stock_movements", "price_alerts",
          "leave_requests", "tables", "table_orders", "tips", "attendance", "kitchen_tickets"}
current_rid: ContextVar[str | None] = ContextVar("restaurant_id", default=None)


def specific_rid() -> str:
    rid = current_rid.get()
    if not rid or rid == "all":
        raise HTTPException(status_code=400, detail="Kayıt eklemek için üstten bir restoran seçin")
    return rid


def _scoped(filter: Dict[str, Any] | None) -> Dict[str, Any]:
    f = dict(filter or {})
    rid = current_rid.get()
    if rid and rid != "all":
        f["restaurant_id"] = rid
    return f


class ScopedCollection:
    """Mongo collection that only sees and writes rows of the selected restaurant."""

    def __init__(self, raw):
        self.raw = raw

    def find(self, filter=None, *args, **kwargs):
        return self.raw.find(_scoped(filter), *args, **kwargs)

    async def find_one(self, filter=None, *args, **kwargs):
        return await self.raw.find_one(_scoped(filter), *args, **kwargs)

    async def count_documents(self, filter, **kwargs):
        return await self.raw.count_documents(_scoped(filter), **kwargs)

    async def insert_one(self, doc, **kwargs):
        if not doc.get("restaurant_id"):
            doc["restaurant_id"] = specific_rid()
        return await self.raw.insert_one(doc, **kwargs)

    async def replace_one(self, filter, doc, **kwargs):
        if not doc.get("restaurant_id"):
            old = await self.raw.find_one(_scoped(filter), {"restaurant_id": 1})
            doc["restaurant_id"] = (old or {}).get("restaurant_id") or specific_rid()
        return await self.raw.replace_one(_scoped(filter), doc, **kwargs)

    async def update_one(self, filter, update, **kwargs):
        return await self.raw.update_one(_scoped(filter), update, **kwargs)

    async def update_many(self, filter, update, **kwargs):
        return await self.raw.update_many(_scoped(filter), update, **kwargs)

    async def delete_many(self, filter, **kwargs):
        return await self.raw.delete_many(_scoped(filter), **kwargs)

    async def find_one_and_update(self, filter, update, **kwargs):
        return await self.raw.find_one_and_update(_scoped(filter), update, **kwargs)

    async def find_one_and_delete(self, filter, *args, **kwargs):
        return await self.raw.find_one_and_delete(_scoped(filter), *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.raw, name)


class ScopedDB:
    def __init__(self, raw):
        self.raw = raw

    def __getitem__(self, name):
        return ScopedCollection(self.raw[name]) if name in SCOPED else self.raw[name]

    def __getattr__(self, name):
        return self[name]
