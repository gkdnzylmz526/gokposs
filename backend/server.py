import asyncio
import logging
import os
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")
client = AsyncIOMotorClient(os.environ["MONGO_URL"])
db = client[os.environ["DB_NAME"]]
api = APIRouter(prefix="/api")

class Entry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class SalesEntry(Entry):
    channel: str = "Salon"
    amount: float = 0
    note: str = ""

class ExpenseEntry(Entry):
    category: str = "Diğer"
    amount: float = 0
    note: str = ""

class InventoryEntry(Entry):
    name: str
    quantity: float = 0
    unit: str = "adet"
    minimum: float = 0

class StaffEntry(Entry):
    name: str
    shift: str = "09:00 – 17:00"
    task: str = ""
    status: str = "Bekliyor"

class CashEntry(Entry):
    opening: float = 0
    closing: float = 0
    note: str = ""

COLLECTIONS = {"sales": SalesEntry, "expenses": ExpenseEntry, "inventory": InventoryEntry, "staff": StaffEntry, "cash": CashEntry}

async def list_items(collection: str) -> List[Dict[str, Any]]:
    return await db[collection].find({}, {"_id": 0}).sort("created_at", -1).to_list(100)

@api.get("/")
async def root():
    return {"message": "Restoran Asistanı hazır"}

@api.get("/dashboard")
async def dashboard():
    sales = await list_items("sales")
    expenses = await list_items("expenses")
    inventory = await list_items("inventory")
    staff = await list_items("staff")
    cash = await list_items("cash")
    revenue = sum(float(item.get("amount", 0)) for item in sales)
    spent = sum(float(item.get("amount", 0)) for item in expenses)
    low_stock = sum(1 for item in inventory if float(item.get("quantity", 0)) <= float(item.get("minimum", 0)))
    return {"revenue": revenue, "expenses": spent, "profit": revenue - spent, "low_stock": low_stock, "staff_count": len(staff), "sales": sales, "expenses_list": expenses, "inventory": inventory, "staff": staff, "cash": cash}

def make_crud(name: str, model: type[BaseModel]):
    @api.get(f"/{name}")
    async def get_items():
        return await list_items(name)
    @api.post(f"/{name}", response_model=model)
    async def create_item(item: model):
        doc = item.model_dump()
        await db[name].insert_one(doc)
        return item
    @api.delete(f"/{name}/{{item_id}}")
    async def delete_item(item_id: str):
        result = await db[name].delete_one({"id": item_id})
        if not result.deleted_count:
            raise HTTPException(status_code=404, detail="Kayıt bulunamadı")
        return {"ok": True}
    return get_items, create_item, delete_item

for collection_name, collection_model in COLLECTIONS.items():
    make_crud(collection_name, collection_model)

app = FastAPI(title="Restoran Asistanı API")
app.include_router(api)
app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","), allow_methods=["*"], allow_headers=["*"])

@app.on_event("shutdown")
async def shutdown():
    client.close()