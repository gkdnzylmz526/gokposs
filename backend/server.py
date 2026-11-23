import asyncio
import hmac
import re
import logging
import os
import uuid
from contextlib import suppress
from datetime import date as date_cls, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any, Dict, List

from dotenv import load_dotenv
from fastapi import APIRouter, BackgroundTasks, FastAPI, HTTPException, Query, Request
from pymongo.errors import DuplicateKeyError
from fastapi.responses import Response

from exports import build_excel, build_pdf
from mailer import send_report_email
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")
client = AsyncIOMotorClient(os.environ["MONGO_URL"])
db = client[os.environ["DB_NAME"]]
api = APIRouter(prefix="/api")
TZ = ZoneInfo("Europe/Istanbul")

def local_day(value: str) -> str:
    return datetime.fromisoformat(value).astimezone(TZ).date().isoformat()

class Entry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class SalesEntry(Entry):
    product_id: str = ""
    product_name: str = ""
    quantity: float = 1
    unit_price: float = 0
    unit_cost: float = 0
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

class RecipeItem(BaseModel):
    inventory_id: str
    amount: float

class ProductEntry(Entry):
    name: str
    category: str = "Genel"
    price: float = 0
    cost: float = 0
    active: bool = True
    recipe: List[RecipeItem] = []

COLLECTIONS = {"sales": SalesEntry, "expenses": ExpenseEntry, "inventory": InventoryEntry, "staff": StaffEntry, "cash": CashEntry, "products": ProductEntry}

async def list_items(collection: str, since: str | None = None, limit: int | None = 100, until: str | None = None) -> List[Dict[str, Any]]:
    query = {"created_at": {k: v for k, v in (("$gte", since), ("$lt", until)) if v}} if since or until else {}
    return await db[collection].find(query, {"_id": 0}).sort("created_at", -1).to_list(limit)

def _total(items) -> float:
    return sum(float(item.get("amount", 0)) for item in items)

@api.get("/")
async def root():
    return {"message": "GÖKBOSS POS hazır"}

@api.get("/dashboard")
async def dashboard():
    sales = await list_items("sales")
    expenses = await list_items("expenses")
    inventory = await list_items("inventory")
    staff = await list_items("staff")
    cash = await list_items("cash")
    products = await list_items("products")
    today = datetime.now(TZ).date()
    week_start = datetime.combine(today - timedelta(days=6), datetime.min.time(), TZ).astimezone(timezone.utc).isoformat()
    week_sales = await list_items("sales", week_start, None)
    week_expenses = await list_items("expenses", week_start, None)
    weekly = []
    for offset in range(6, -1, -1):
        day = (today - timedelta(days=offset)).isoformat()
        weekly.append({"date": day, "revenue": _total(i for i in week_sales if local_day(i["created_at"]) == day), "expenses": _total(i for i in week_expenses if local_day(i["created_at"]) == day)})
    revenue, spent = weekly[-1]["revenue"], weekly[-1]["expenses"]
    low_stock = sum(1 for item in inventory if float(item.get("quantity", 0)) <= float(item.get("minimum", 0)))
    return {"revenue": revenue, "expenses": spent, "profit": revenue - spent, "low_stock": low_stock, "staff_count": len(staff), "weekly": weekly, "sales": sales, "expenses_list": expenses, "inventory": inventory, "staff": staff, "cash": cash, "products": products}

PERIOD = Query("daily", pattern="^(daily|weekly|monthly|custom)$")

def _day_start(day) -> datetime:
    return datetime.combine(day, datetime.min.time(), TZ)

def _range(period: str, start: str | None, end: str | None):
    today = datetime.now(TZ).date()
    if period != "custom":
        return _day_start(today - timedelta(days={"daily": 0, "weekly": 6, "monthly": 29}[period])), _day_start(today + timedelta(days=1))
    try:
        first, last = date_cls.fromisoformat(start or ""), date_cls.fromisoformat(end or "")
    except ValueError:
        raise HTTPException(status_code=422, detail="Başlangıç ve bitiş tarihi gerekli (YYYY-AA-GG)")
    if first > last:
        raise HTTPException(status_code=422, detail="Başlangıç tarihi bitişten sonra olamaz")
    return _day_start(first), _day_start(last + timedelta(days=1))

async def build_report(period: str, start: str | None = None, end: str | None = None) -> Dict[str, Any]:
    begin, finish = _range(period, start, end)
    since, until = begin.astimezone(timezone.utc).isoformat(), finish.astimezone(timezone.utc).isoformat()
    sales = await list_items("sales", since, None, until)
    expenses = await list_items("expenses", since, None, until)
    products = {}
    for item in sales:
        name = item.get("product_name") or item.get("note") or "Diğer satış"
        row = products.setdefault(name, {"product_name": name, "quantity": 0, "revenue": 0, "cost": 0, "profit": 0})
        quantity = float(item.get("quantity", 1))
        row["quantity"] += quantity
        row["revenue"] += float(item.get("amount", 0))
        row["cost"] += quantity * float(item.get("unit_cost", 0))
        row["profit"] = row["revenue"] - row["cost"]
    revenue, spent = _total(sales), _total(expenses)
    return {"period": period, "start": begin.isoformat(), "end": (finish - timedelta(seconds=1)).isoformat(), "revenue": revenue, "expenses": spent, "profit": revenue - spent, "sales_count": len(sales),
            "top_products": sorted(products.values(), key=lambda row: row["quantity"], reverse=True), "sales": sales, "expenses_list": expenses}

async def full_report(period: str, start: str | None = None, end: str | None = None) -> Dict[str, Any]:
    report = await build_report(period, start, end)
    report["reconciliation"] = await cash_reconciliation(None if period != "custom" else end)
    return report

@api.get("/reports")
async def reports(period: str = PERIOD, start: str | None = None, end: str | None = None):
    return await build_report(period, start, end)

@api.get("/reports/export")
async def export_report(period: str = PERIOD, format: str = Query("xlsx", pattern="^(xlsx|pdf)$"), start: str | None = None, end: str | None = None):
    report = await full_report(period, start, end)
    name = f"gokboss-pos-{period}-rapor-{report['start'][:10]}_{report['end'][:10]}.{format}"
    if format == "pdf":
        return Response(build_pdf(report), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})
    return Response(build_excel(report), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="{name}"'})

async def send_daily_report(trigger: str, key: str | None = None) -> Dict[str, Any]:
    day = datetime.now(TZ).date().isoformat()
    record = {"id": str(uuid.uuid4()), "date": day, "trigger": trigger, "key": key, "recipient": os.environ.get("REPORT_RECIPIENT", ""), "created_at": datetime.now(timezone.utc).isoformat()}
    try:
        report = await full_report("daily")
        await asyncio.to_thread(send_report_email, build_pdf(report), report, day)
        record["status"] = "sent"
    except Exception as exc:
        logging.exception("Daily report email failed")
        record.update(status="failed", error=f"{type(exc).__name__}: {str(exc)[:200]}")
    await db.report_deliveries.insert_one({**record})
    return record

@api.post("/cron/daily-report")
async def cron_daily_report(request: Request, background: BackgroundTasks):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    secret = os.environ.get("WEBHOOK_CRON_SECRET", "")
    auth = request.headers.get("authorization", "")
    if not secret or not auth.startswith("Bearer ") or not hmac.compare_digest(auth[7:], secret):
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid body")
    run_id = request.headers.get("x-webhook-id") or (body or {}).get("run_id") or str(uuid.uuid4())
    try:
        await db.cron_runs.insert_one({"run_id": run_id, "created_at": datetime.now(timezone.utc).isoformat()})
    except DuplicateKeyError:
        return {"status": "duplicate"}
    background.add_task(send_daily_report, "cron", run_id)
    return {"status": "accepted"}

@api.post("/email/send-now")
async def email_send_now():
    record = await send_daily_report("manual")
    if record["status"] != "sent":
        raise HTTPException(status_code=502, detail="E-posta gönderilemedi. Gmail bilgilerini kontrol edin.")
    return {"status": "sent", "recipient": record["recipient"]}

@api.get("/email/status")
async def email_status():
    last = await db.report_deliveries.find({}, {"_id": 0}).sort("created_at", -1).to_list(5)
    return {"recipient": os.environ.get("REPORT_RECIPIENT", ""), "configured": bool(os.environ.get("GMAIL_USERNAME") and os.environ.get("GMAIL_APP_PASSWORD")), "schedule": "Her gece 23:59", "history": last}

@api.get("/cash/reconciliation")
async def cash_reconciliation(date: str | None = None):
    target = date or datetime.now(TZ).date().isoformat()
    since = datetime.combine(datetime.fromisoformat(target).date(), datetime.min.time(), TZ).astimezone(timezone.utc).isoformat()
    def same_day(item):
        return local_day(item["created_at"]) == target
    sales = [item for item in await list_items("sales", since, None) if same_day(item)]
    expenses = [item for item in await list_items("expenses", since, None) if same_day(item)]
    cash_logs = [item for item in await list_items("cash", since, None) if same_day(item)]
    opening = float(cash_logs[-1].get("opening", 0)) if cash_logs else 0
    actual = float(cash_logs[0].get("closing", 0)) if cash_logs else 0
    sales_total, expenses_total = _total(sales), _total(expenses)
    expected = opening + sales_total - expenses_total
    return {"date": target, "opening": opening, "sales": sales_total, "expenses": expenses_total, "expected_closing": expected, "actual_closing": actual, "difference": actual - expected, "has_closing": bool(cash_logs)}

async def apply_stock(sale: Dict[str, Any], sign: int) -> None:
    quantity = float(sale.get("quantity", 1)) * sign
    product = await db.products.find_one({"id": sale.get("product_id")}) if sale.get("product_id") else None
    if not product and sale.get("product_name"):
        product = await db.products.find_one({"name": {"$regex": f"^{re.escape(sale['product_name'].strip())}$", "$options": "i"}})
    if product and product.get("recipe"):
        for item in product["recipe"]:
            await db.inventory.update_one({"id": item["inventory_id"]}, {"$inc": {"quantity": -float(item["amount"]) * quantity}})
    elif sale.get("product_name"):
        await db.inventory.update_one({"name": {"$regex": f"^{re.escape(sale['product_name'].strip())}$", "$options": "i"}}, {"$inc": {"quantity": -quantity}})

def make_crud(name: str, model: type[BaseModel]):
    @api.get(f"/{name}")
    async def get_items():
        return await list_items(name)
    @api.post(f"/{name}", response_model=model)
    async def create_item(item: model):
        doc = item.model_dump()
        await db[name].insert_one({**doc})
        if name == "sales":
            await apply_stock(doc, 1)
        return item
    @api.put(f"/{name}/{{item_id}}", response_model=model)
    async def update_item(item_id: str, item: model):
        old = await db[name].find_one({"id": item_id}, {"_id": 0})
        if not old:
            raise HTTPException(status_code=404, detail="Kayıt bulunamadı")
        doc = {**item.model_dump(), "id": item_id, "created_at": old["created_at"]}
        await db[name].replace_one({"id": item_id}, doc)
        if name == "sales":
            await apply_stock(old, -1)
            await apply_stock(doc, 1)
        return model(**doc)
    @api.delete(f"/{name}/{{item_id}}")
    async def delete_item(item_id: str):
        old = await db[name].find_one_and_delete({"id": item_id}, {"_id": 0})
        if not old:
            raise HTTPException(status_code=404, detail="Kayıt bulunamadı")
        if name == "sales":
            await apply_stock(old, -1)
        return {"ok": True}
    return get_items, create_item, update_item, delete_item

for collection_name, collection_model in COLLECTIONS.items():
    make_crud(collection_name, collection_model)

app = FastAPI(title="GÖKBOSS POS API")
app.include_router(api)
app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","), allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
async def startup():
    await db.cron_runs.create_index("run_id", unique=True)

@app.on_event("shutdown")
async def shutdown():
    client.close()