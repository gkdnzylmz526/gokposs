import asyncio
import hmac
import math
import json
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
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from fastapi.responses import Response

from exports import build_excel, build_pdf
from mailer import send_report_email, send_weekly_email
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
    stock_moves: List[Dict[str, Any]] = []

class PurchaseItem(BaseModel):
    inventory_id: str
    quantity: float = Field(gt=0)
    unit_price: float = Field(default=0, ge=0)

class ExpenseEntry(Entry):
    category: str = "Diğer"
    amount: float = 0
    note: str = ""
    supplier: str = ""
    purchases: List[PurchaseItem] = []
    stock_moves: List[Dict[str, Any]] = []

class ShiftEntry(Entry):
    staff_id: str = Field(min_length=1)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    start: str = Field(default="09:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    end: str = Field(default="17:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    task: str = ""

class SupplierEntry(Entry):
    name: str
    phone: str = ""
    note: str = ""

class InventoryEntry(Entry):
    name: str
    quantity: float = 0
    unit: str = "adet"
    minimum: float = 0
    unit_cost: float = 0
    target: float = 0
    supplier: str = ""

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
    cost_from_recipe: bool = False
    target_margin: float = 0

COLLECTIONS = {"sales": SalesEntry, "expenses": ExpenseEntry, "inventory": InventoryEntry, "staff": StaffEntry, "cash": CashEntry, "products": ProductEntry, "suppliers": SupplierEntry, "shifts": ShiftEntry}

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
    inventory = await list_items("inventory", limit=None)
    staff = await list_items("staff", limit=None)
    cash = await list_items("cash")
    products = await list_items("products", limit=None)
    suppliers = await list_items("suppliers", limit=None)
    shifts = await db.shifts.find({}, {"_id": 0}).sort([("date", 1), ("start", 1)]).to_list(None)
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
    return {"revenue": revenue, "expenses": spent, "profit": revenue - spent, "low_stock": low_stock, "staff_count": len(staff), "weekly": weekly, "sales": sales, "expenses_list": expenses, "inventory": inventory, "staff": staff, "cash": cash, "products": products, "suppliers": suppliers, "shifts": shifts}

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

async def _deliver(kind: str, trigger: str, key: str | None, job) -> Dict[str, Any]:
    day = datetime.now(TZ).date().isoformat()
    record = {"id": str(uuid.uuid4()), "kind": kind, "date": day, "trigger": trigger, "key": key, "recipient": os.environ.get("REPORT_RECIPIENT", ""), "created_at": datetime.now(timezone.utc).isoformat()}
    try:
        await job(day)
        record["status"] = "sent"
    except Exception as exc:
        logging.exception("Daily report email failed")
        record.update(status="failed", error=f"{type(exc).__name__}: {str(exc)[:200]}")
    await db.report_deliveries.insert_one({**record})
    return record

async def send_daily_report(trigger: str, key: str | None = None) -> Dict[str, Any]:
    async def job(day):
        report = await full_report("daily")
        report["low_stock"] = [i for i in await list_items("inventory", limit=None) if float(i.get("quantity", 0)) <= float(i.get("minimum", 0))]
        await asyncio.to_thread(send_report_email, build_pdf(report), report, day)
    return await _deliver("daily", trigger, key, job)

async def send_weekly_summary(trigger: str, key: str | None = None) -> Dict[str, Any]:
    async def job(day):
        today = datetime.now(TZ).date()
        start, end = today - timedelta(days=today.weekday() + 7), today - timedelta(days=today.weekday() + 1)
        report = await build_report("custom", start.isoformat(), end.isoformat())
        await asyncio.to_thread(send_weekly_email, report, f"{start.strftime('%d.%m.%Y')} – {end.strftime('%d.%m.%Y')}")
    return await _deliver("weekly", trigger, key, job)

async def accept_cron(request: Request) -> str | None:
    secret = os.environ.get("WEBHOOK_CRON_SECRET", "")
    auth = request.headers.get("authorization", "")
    if not secret or not auth.startswith("Bearer ") or not hmac.compare_digest(auth[7:], secret):
        raise HTTPException(status_code=401, detail="Unauthorized")
    raw = await request.body()
    try:
        body = json.loads(raw) if raw.strip() else {}
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid body")
    run_id = request.headers.get("x-webhook-id") or (body.get("run_id") if isinstance(body, dict) else None) or str(uuid.uuid4())
    try:
        await db.cron_runs.insert_one({"run_id": run_id, "created_at": datetime.now(timezone.utc).isoformat()})
    except DuplicateKeyError:
        return None
    return run_id

@api.post("/cron/daily-report")
async def cron_daily_report(request: Request, background: BackgroundTasks):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    run_id = await accept_cron(request)
    if not run_id:
        return {"status": "duplicate"}
    background.add_task(send_daily_report, "cron", run_id)
    return {"status": "accepted"}

@api.post("/cron/weekly-summary")
async def cron_weekly_summary(request: Request, background: BackgroundTasks):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    run_id = await accept_cron(request)
    if not run_id:
        return {"status": "duplicate"}
    background.add_task(send_weekly_summary, "cron", run_id)
    return {"status": "accepted"}

@api.post("/email/send-now")
async def email_send_now(kind: str = Query("daily", pattern="^(daily|weekly)$")):
    record = await (send_weekly_summary if kind == "weekly" else send_daily_report)("manual")
    if record["status"] != "sent":
        return {"status": "failed", "detail": "E-posta gönderilemedi. Gmail bilgilerini kontrol edin."}
    return {"status": "sent", "recipient": record["recipient"]}

@api.get("/email/status")
async def email_status():
    last = await db.report_deliveries.find({}, {"_id": 0}).sort("created_at", -1).to_list(5)
    return {"recipient": os.environ.get("REPORT_RECIPIENT", ""), "configured": bool(os.environ.get("GMAIL_USERNAME") and os.environ.get("GMAIL_APP_PASSWORD")), "schedule": "Her gece 23:59", "weekly_schedule": "Her pazartesi 09:00", "history": last}

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

def _tr_key(value: str) -> str:
    return (value or "").replace("I", "ı").replace("İ", "i").lower().strip()

async def stock_moves(sale: Dict[str, Any]) -> List[Dict[str, Any]]:
    quantity = float(sale.get("quantity", 1))
    key = _tr_key(sale.get("product_name", ""))
    product = await db.products.find_one({"id": sale.get("product_id")}, {"_id": 0}) if sale.get("product_id") else None
    if not product and key:
        product = next((p for p in await list_items("products", limit=None) if _tr_key(p["name"]) == key), None)
    if product and product.get("recipe"):
        return [{"inventory_id": r["inventory_id"], "delta": -float(r["amount"]) * quantity} for r in product["recipe"]]
    match = next((i for i in await list_items("inventory", limit=None) if key and _tr_key(i["name"]) == key), None)
    return [{"inventory_id": match["id"], "delta": -quantity}] if match else []

async def log_movement(item: Dict[str, Any], delta: float, reason: str, sale: Dict[str, Any] | None = None) -> None:
    await db.stock_movements.insert_one({"id": str(uuid.uuid4()), "inventory_id": item["id"], "inventory_name": item["name"], "unit": item.get("unit", ""), "delta": round(delta, 3),
        "quantity_after": item["quantity"], "reason": reason, "sale_id": (sale or {}).get("id", ""), "product_name": (sale or {}).get("product_name", ""),
        "sale_quantity": (sale or {}).get("quantity", 0), "created_at": datetime.now(timezone.utc).isoformat()})

async def apply_moves(moves: List[Dict[str, Any]], sign: int, sale: Dict[str, Any], reason: str) -> None:
    for move in moves:
        delta = move["delta"] * sign
        item = await db.inventory.find_one_and_update({"id": move["inventory_id"]}, [{"$set": {"quantity": {"$round": [{"$add": ["$quantity", delta]}, 3]}}}], projection={"_id": 0}, return_document=ReturnDocument.AFTER)
        if item:
            await log_movement(item, delta, reason, sale)

@api.get("/stock-movements")
async def get_stock_movements(inventory_id: str | None = None):
    query = {"inventory_id": inventory_id} if inventory_id else {}
    return await db.stock_movements.find(query, {"_id": 0}).sort("created_at", -1).to_list(200)

async def with_recipe_cost(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc.get("recipe"):
        return {**doc, "cost_from_recipe": False}
    prices = {i["id"]: float(i.get("unit_cost", 0)) for i in await list_items("inventory", limit=None)}
    cost = sum(float(r["amount"]) * prices.get(r["inventory_id"], 0) for r in doc["recipe"])
    return {**doc, "cost": round(cost, 2), "cost_from_recipe": True}

async def recompute_product_costs() -> None:
    for product in await list_items("products", limit=None):
        if product.get("recipe"):
            updated = await with_recipe_cost(product)
            await db.products.update_one({"id": product["id"]}, {"$set": {"cost": updated["cost"], "cost_from_recipe": True}})

def suggested_amount(item: Dict[str, Any]) -> float:
    target = float(item.get("target") or 0) or float(item.get("minimum", 0)) * 2
    return round(max(target - float(item.get("quantity", 0)), 0), 3)

@api.get("/order-list")
async def order_list():
    groups: Dict[str, Dict[str, Any]] = {}
    phones = {_tr_key(x["name"]): x.get("phone", "") for x in await list_items("suppliers", limit=None)}
    for item in await list_items("inventory", limit=None):
        if float(item.get("quantity", 0)) > float(item.get("minimum", 0)):
            continue
        amount = suggested_amount(item)
        if not amount:
            continue
        supplier = item.get("supplier") or "Tedarikçi belirtilmemiş"
        group = groups.setdefault(supplier, {"supplier": supplier, "phone": phones.get(_tr_key(item.get("supplier", "")), ""), "items": [], "estimated_total": 0})
        cost = round(amount * float(item.get("unit_cost", 0)), 2)
        group["items"].append({"inventory_id": item["id"], "name": item["name"], "unit": item.get("unit", ""), "quantity": item.get("quantity", 0), "minimum": item.get("minimum", 0), "suggested": amount, "estimated_cost": cost})
        group["estimated_total"] = round(group["estimated_total"] + cost, 2)
    return sorted(groups.values(), key=lambda g: g["supplier"])

async def apply_purchases(doc: Dict[str, Any], sign: int, reason: str) -> None:
    moves = [{"inventory_id": p["inventory_id"], "delta": float(p["quantity"])} for p in doc.get("purchases", [])]
    await apply_moves(moves, sign, {"id": doc["id"], "product_name": ""}, reason)
    increases = []
    before = {p["id"]: p for p in await list_items("products", limit=None)}
    if sign > 0:
        for p in doc.get("purchases", []):
            price = float(p.get("unit_price", 0))
            if price > 0:
                item = await db.inventory.find_one_and_update({"id": p["inventory_id"]}, {"$set": {"unit_cost": price}}, projection={"_id": 0})
                old_price = float((item or {}).get("unit_cost", 0))
                if item and old_price > 0 and price >= old_price * (1 + PRICE_ALERT_PCT / 100):
                    increases.append((item, old_price, price))
    doc["stock_moves"] = moves if sign > 0 else []
    await recompute_product_costs()
    for item, old_price, price in increases:
        await create_price_alert(item, old_price, price, before)

PRICE_ALERT_PCT = 10

def _margin(price: float, cost: float) -> float:
    return round((price - cost) / price * 100, 1) if price else 0

async def create_price_alert(item: Dict[str, Any], old_price: float, new_price: float, before: Dict[str, Dict[str, Any]]) -> None:
    affected = []
    for product in await list_items("products", limit=None):
        if any(r["inventory_id"] == item["id"] for r in product.get("recipe", [])):
            old_cost = float(before.get(product["id"], product).get("cost", 0))
            price = float(product.get("price", 0))
            affected.append({"product_id": product["id"], "name": product["name"], "price": price, "old_cost": old_cost, "new_cost": float(product.get("cost", 0)),
                             "old_margin": _margin(price, old_cost), "new_margin": _margin(price, float(product.get("cost", 0)))})
    await db.price_alerts.insert_one({"id": str(uuid.uuid4()), "inventory_id": item["id"], "inventory_name": item["name"], "unit": item.get("unit", ""),
        "old_price": old_price, "new_price": new_price, "change_pct": round((new_price - old_price) / old_price * 100, 1), "affected": affected,
        "dismissed": False, "created_at": datetime.now(timezone.utc).isoformat()})

@api.get("/price-alerts")
async def price_alerts():
    return await db.price_alerts.find({"dismissed": False}, {"_id": 0}).sort("created_at", -1).to_list(50)

@api.post("/price-alerts/{alert_id}/dismiss")
async def dismiss_price_alert(alert_id: str):
    result = await db.price_alerts.update_one({"id": alert_id}, {"$set": {"dismissed": True}})
    if not result.matched_count:
        raise HTTPException(status_code=404, detail="Uyarı bulunamadı")
    return {"ok": True}

def suggested_price(product: Dict[str, Any]) -> float | None:
    margin = float(product.get("target_margin") or 0) or 65
    cost = float(product.get("cost", 0))
    return math.ceil(cost / (1 - margin / 100)) if cost > 0 and margin < 100 else None

@api.post("/products/apply-suggested")
async def apply_suggested_prices(payload: Dict[str, List[str]]):
    ids = set(payload.get("product_ids", []))
    changed = []
    for product in await list_items("products", limit=None):
        price = suggested_price(product)
        if product["id"] in ids and price and price != float(product.get("price", 0)):
            await db.products.update_one({"id": product["id"]}, {"$set": {"price": price}})
            changed.append({"id": product["id"], "name": product["name"], "old_price": product.get("price", 0), "new_price": price})
    return {"updated": changed}

def _expense_supplier(doc: Dict[str, Any], inventory: Dict[str, Dict[str, Any]]) -> str:
    if doc.get("supplier"):
        return doc["supplier"]
    names = {inventory.get(p["inventory_id"], {}).get("supplier", "") for p in doc.get("purchases", [])} - {""}
    return names.pop() if len(names) == 1 else ("Birden fazla tedarikçi" if names else "")

@api.get("/suppliers/spending")
async def supplier_spending(months: int = Query(6, ge=1, le=24)):
    today = datetime.now(TZ).date().replace(day=1)
    keys = []
    y, m = today.year, today.month
    for _ in range(months):
        keys.insert(0, f"{y}-{m:02d}")
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    since = _day_start(date_cls.fromisoformat(keys[0] + "-01")).astimezone(timezone.utc).isoformat()
    inventory = {i["id"]: i for i in await list_items("inventory", limit=None)}
    rows: Dict[str, Dict[str, Any]] = {}
    for exp in await list_items("expenses", since, None):
        supplier = _expense_supplier(exp, inventory)
        if not supplier:
            continue
        month = datetime.fromisoformat(exp["created_at"]).astimezone(TZ).strftime("%Y-%m")
        row = rows.setdefault(supplier, {"supplier": supplier, "months": {k: 0 for k in keys}, "total": 0, "count": 0})
        row["months"][month] = round(row["months"].get(month, 0) + float(exp.get("amount", 0)), 2)
        row["total"] = round(row["total"] + float(exp.get("amount", 0)), 2)
        row["count"] += 1
    return {"months": keys, "rows": sorted(rows.values(), key=lambda r: -r["total"])}

def _purchase_total(doc: Dict[str, Any]) -> None:
    if doc.get("purchases") and not float(doc.get("amount", 0)):
        doc["amount"] = round(sum(float(p["quantity"]) * float(p.get("unit_price", 0)) for p in doc["purchases"]), 2)

async def fill_sale_cost(doc: Dict[str, Any]) -> None:
    if not doc.get("unit_cost") and doc.get("product_id"):
        product = await db.products.find_one({"id": doc["product_id"]}, {"_id": 0, "cost": 1})
        doc["unit_cost"] = float((product or {}).get("cost", 0))

def make_crud(name: str, model: type[BaseModel]):
    @api.get(f"/{name}")
    async def get_items():
        return await list_items(name)
    @api.post(f"/{name}", response_model=model)
    async def create_item(item: model):
        doc = item.model_dump()
        if name == "products":
            doc = await with_recipe_cost(doc)
        if name == "sales":
            await fill_sale_cost(doc)
            doc["stock_moves"] = await stock_moves(doc)
            await apply_moves(doc["stock_moves"], 1, doc, "Satış")
        if name == "expenses" and doc.get("purchases"):
            _purchase_total(doc)
            await apply_purchases(doc, 1, f"Alış · {doc['category']}")
        await db[name].insert_one({**doc})
        if name == "inventory" and doc["quantity"]:
            await log_movement(doc, doc["quantity"], "İlk kayıt")
        if name == "inventory":
            await recompute_product_costs()
        return model(**doc)
    @api.put(f"/{name}/{{item_id}}", response_model=model)
    async def update_item(item_id: str, item: model):
        old = await db[name].find_one({"id": item_id}, {"_id": 0})
        if not old:
            raise HTTPException(status_code=404, detail="Kayıt bulunamadı")
        doc = {**item.model_dump(), "id": item_id, "created_at": old["created_at"]}
        if name == "products":
            doc = await with_recipe_cost(doc)
        if name == "expenses" and (old.get("purchases") or doc.get("purchases")):
            await apply_purchases(old, -1, "Alış düzeltildi (eski kayıt geri alındı)")
            old_total = sum(float(p["quantity"]) * float(p.get("unit_price", 0)) for p in old.get("purchases", []))
            if old.get("purchases") and abs(float(old.get("amount", 0)) - old_total) < 0.01 and abs(float(doc.get("amount", 0)) - old_total) < 0.01:
                doc["amount"] = 0
            _purchase_total(doc)
            await apply_purchases(doc, 1, f"Alış düzeltildi · {doc['category']}")
        if name == "sales":
            await fill_sale_cost(doc)
            await apply_moves(old.get("stock_moves", []), -1, old, "Satış düzeltildi (eski kayıt geri alındı)")
            doc["stock_moves"] = await stock_moves(doc)
            await apply_moves(doc["stock_moves"], 1, doc, "Satış düzeltildi (yeni kayıt)")
        await db[name].replace_one({"id": item_id}, doc)
        if name == "inventory" and float(doc["quantity"]) != float(old.get("quantity", 0)):
            await log_movement(doc, float(doc["quantity"]) - float(old.get("quantity", 0)), "Manuel sayım / düzeltme")
        if name == "inventory":
            await recompute_product_costs()
        return model(**doc)
    @api.delete(f"/{name}/{{item_id}}")
    async def delete_item(item_id: str):
        old = await db[name].find_one_and_delete({"id": item_id}, {"_id": 0})
        if not old:
            raise HTTPException(status_code=404, detail="Kayıt bulunamadı")
        if name == "sales":
            await apply_moves(old.get("stock_moves", []), -1, old, "Satış silindi (stok iade)")
        if name == "expenses" and old.get("purchases"):
            await apply_purchases(old, -1, "Alış silindi (stoktan çıkarıldı)")
        if name == "staff":
            await db.shifts.delete_many({"staff_id": item_id})
        if name == "inventory":
            await log_movement({**old, "quantity": 0}, -float(old.get("quantity", 0)), "Malzeme silindi")
            await recompute_product_costs()
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