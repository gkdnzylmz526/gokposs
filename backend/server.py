import asyncio
import hmac
import secrets
import math
import json
import re
import logging
import os
import uuid
from urllib.parse import quote
from contextlib import suppress
from datetime import date as date_cls, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any, Dict, List

from dotenv import load_dotenv
from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from fastapi.responses import Response, StreamingResponse

from exports import build_excel, build_pdf, build_payroll_excel, build_payslip_pdf
from mailer import send_cash_reminder_email, send_leave_request_email, send_missing_revenue_email, send_monthly_email, send_pin_request_email, send_report_email, send_restaurant_daily_email, send_weekly_email
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")
client = AsyncIOMotorClient(os.environ["MONGO_URL"])
from storage import APP_PREFIX, get_object, init_storage, put_object
import ai
import restaurants as rest
from scope import DEFAULT_RESTAURANT, RESTAURANT_IDS, RESTAURANT_NAMES, RESTAURANTS, SCOPED, ScopedDB, current_rid, specific_rid
db = ScopedDB(client[os.environ["DB_NAME"]])
try:  # launched as `backend.server` (the default)
    from backend.clerk_auth import clerk_router, require_user
except ModuleNotFoundError:  # launched from inside backend/ as `server`
    from clerk_auth import clerk_router, require_user
import requests as http_requests
from pymongo import ReturnDocument as _RD

# The role list is code, so every publish ships it to Live. Highest first; keep `admin`.
ROLES = ["admin", "manager", "staff", "member"]
DEFAULT_ROLE = "member"
RETIRED_ROLES: Dict[str, str] = {}
RANK = {r: len(ROLES) - i for i, r in enumerate(ROLES)}
ENV = "live" if os.environ.get("CLERK_PUBLISHABLE_KEY", "").startswith("pk_live_") else "preview"
IN_ENV = {"env": {"$in": [ENV, None]}}
PUBLIC_PREFIXES = ("/api/public/", "/api/cron/")

def effective_role(role) -> str:
    role = RETIRED_ROLES.get(role, role)
    return role if role in ROLES else DEFAULT_ROLE

def _clerk_user(user_id: str) -> Dict[str, Any]:
    r = http_requests.get(f"https://api.clerk.com/v1/users/{user_id}", timeout=10,
                          headers={"Authorization": f"Bearer {os.environ['CLERK_SECRET_KEY']}", "User-Agent": "emergent-app"})
    r.raise_for_status()
    return r.json()

def _is_admin_email(info: Dict[str, Any]) -> bool:
    admins = {e.strip().lower() for e in os.environ.get("ADMIN_EMAIL", "").split(",") if e.strip()}
    return any(e["email_address"].lower() in admins and (e.get("verification") or {}).get("status") == "verified" for e in info["email_addresses"])

def _restaurant_for_email(info: Dict[str, Any]) -> str | None:
    verified = {e["email_address"].lower() for e in info["email_addresses"] if (e.get("verification") or {}).get("status") == "verified"}
    return next((d["id"] for d in rest.DOCS.values() if not d.get("archived") and (d.get("email") or "").lower() in verified), None)

async def current_member(request: Request) -> Dict[str, Any]:
    user = require_user(request)
    uid = user["user_id"]
    member = await db.users.find_one({"user_id": uid}, {"_id": 0})
    if member is None or not member.get("role"):
        info = await asyncio.to_thread(_clerk_user, uid)
        role = "admin" if _is_admin_email(info) else DEFAULT_ROLE
        email = next((e["email_address"] for e in info["email_addresses"] if e["id"] == info.get("primary_email_address_id")), "")
        home = _restaurant_for_email(info) if role != "admin" else None
        extra = {"role": "manager", "restaurant_id": home} if home else {"role": role}
        await db.users.update_one({"user_id": uid, "role": {"$in": [None, ""]}}, {"$set": extra})
        member = await db.users.find_one_and_update({"user_id": uid}, {"$setOnInsert": {"user_id": uid, **extra, "email": email, "created_at": datetime.now(timezone.utc).isoformat()}},
                                                    upsert=True, projection={"_id": 0}, return_document=_RD.AFTER)
    if member.get("env") != ENV:
        await db.users.update_one({"user_id": uid}, {"$set": {"env": ENV}})
    return {**member, "env": ENV, "role": effective_role(member["role"])}

STAFF_ROUTES = [("GET", r"/api/staff-view"), ("POST", r"/api/sales"), ("POST", r"/api/inventory/[\w-]+/count"), ("GET", r"/api/tables-view"),
                ("POST", r"/api/tables/[\w-]+/(items|close|cancel|pay)"), ("POST", r"/api/tables/[\w-]+/pending/[\w-]+/remove"),
                ("GET", r"/api/kitchen"), ("POST", r"/api/kitchen/[\w-]+/status"), ("GET", r"/api/attendance/me"), ("POST", r"/api/attendance/clock")]
ADMIN_ONLY = r"/api/(users|settings|audit-logs|email|restaurants/manage)(/.*)?"
PIN_FREE = r"/api/(restaurants/(unlock|pin-request|manage(/.*)?)|users(/.*)?|audit-logs|settings(/.*)?)"
ALL_MODE_WRITES = r"/api/(products|menu-order|ai/chat|suppliers|users|email|price-alerts|leave-requests|settings|overhead|restaurants/unlock|restaurants/pin-request|restaurants/manage)(/.*)?|/api/staff/[\w-]+/request-link"

def staff_allowed(method: str, path: str) -> bool:
    return any(method == m and re.fullmatch(p, path) for m, p in STAFF_ROUTES)

def _label(collection: str, doc: Dict[str, Any] | None) -> str:
    doc = doc or {}
    if collection == "sales":
        return f"{doc.get('product_name') or 'Satış'} × {doc.get('quantity', 1):g} · {doc.get('amount', 0):g} ₺"
    if collection in ("expenses", "advances"):
        return f"{doc.get('category') or doc.get('note') or 'Kayıt'} · {doc.get('amount', 0):g} ₺"
    if collection == "cash":
        return f"Açılış {doc.get('opening', 0):g} ₺ · kapanış {doc.get('closing', 0):g} ₺"
    if collection in ("shifts", "leaves"):
        return f"{doc.get('date', '')} {doc.get('start', '')}{'–' + doc['end'] if doc.get('end') else ''} {doc.get('type', '')}".strip()
    if collection == "orders":
        return f"{doc.get('supplier', '')} · {doc.get('status', '')}"
    if collection == "attendance":
        return f"{doc.get('date', '')} {doc.get('start', '')}–{doc.get('end') or '…'}"
    if collection == "tips":
        return f"{doc.get('date', '')} · {doc.get('amount', 0):g} ₺{' · ' + doc['note'] if doc.get('note') else ''}"
    if collection == "tables":
        return f"Masa {doc.get('name', '')}"
    if collection == "incomes":
        return f"{doc.get('date', '')} · {doc.get('category', '')} · {doc.get('amount', 0):g} ₺ {doc.get('payment', '')}"
    if collection == "invoices":
        return f"{doc.get('supplier', '')} · {doc.get('invoice_no') or 'no yok'} · {doc.get('amount', 0):g} ₺"
    return str(doc.get("name") or doc.get("supplier") or doc.get("id", ""))

async def audit(request: Request, action: str, collection: str, item_id: str, doc: Dict[str, Any] | None = None, detail: str = "") -> None:
    member = getattr(request.state, "member", None) or {}
    await db.audit_logs.insert_one({"id": str(uuid.uuid4()), "user_id": member.get("user_id", ""), "user_email": member.get("email", ""), "role": member.get("role", ""),
                                    "restaurant_id": current_rid.get() or "", "action": action, "collection": collection, "item_id": item_id, "summary": detail or _label(collection, doc),
                                    "created_at": datetime.now(timezone.utc).isoformat()})

async def dashboard_guard(request: Request) -> None:
    """Every /api route except the staff leave link and cron webhooks is admin-only."""
    rest.refresh(await db.raw.restaurants.find({}, {"_id": 0}).sort("created_at", 1).to_list(200))
    path = request.url.path
    if path.startswith(PUBLIC_PREFIXES):
        return
    if path in ("/api/me",):
        return
    member = await current_member(request)
    request.state.member = member
    if member["role"] == "staff" and staff_allowed(request.method, path):
        current_rid.set(member.get("restaurant_id") or rest.default_rid())
        return
    if member["role"] not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Bu panele erişim yetkiniz yok")
    if member["role"] == "manager":
        if re.fullmatch(ADMIN_ONLY, path) or (path == "/api/overhead" and request.method != "GET"):
            raise HTTPException(status_code=403, detail="Bu işlem sadece yönetici içindir")
        rid = member.get("restaurant_id")
        if rid not in RESTAURANT_IDS:
            raise HTTPException(status_code=403, detail="Restoranınız arşivlenmiş veya atanmamış")
    else:
        rid = request.headers.get("x-restaurant") or rest.default_rid()
        if rid not in RESTAURANT_IDS and rid != "all":
            raise HTTPException(status_code=400, detail="Geçersiz restoran")
        if rid == "all" and request.method != "GET" and not re.fullmatch(ALL_MODE_WRITES, path):
            raise HTTPException(status_code=400, detail="Bu işlem için üstten bir restoran seçin")
    if not re.fullmatch(PIN_FREE, path):
        rest.require_unlocked(member["user_id"], rid, request.headers.get("x-restaurant-key"))
    current_rid.set(rid)

api = APIRouter(prefix="/api", dependencies=[Depends(dashboard_guard)])
TZ = ZoneInfo("Europe/Istanbul")

def local_day(value: str) -> str:
    return datetime.fromisoformat(value).astimezone(TZ).date().isoformat()

class Entry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class SalesEntry(Entry):
    product_id: str = ""
    product_name: str = ""
    quantity: float = Field(default=1, gt=0)
    unit_price: float = 0
    unit_cost: float = 0
    channel: str = "Salon"
    payment: str = Field(default="Nakit", pattern="^(Nakit|Kart|Yemek kartı)$")
    amount: float = 0
    note: str = ""
    created_by: str = ""
    stock_moves: List[Dict[str, Any]] = []

class PurchaseItem(BaseModel):
    inventory_id: str
    quantity: float = Field(gt=0)
    unit_price: float = Field(default=0, ge=0)

class ExpenseEntry(Entry):
    category: str = "Diğer"
    amount: float = 0
    payment: str = Field(default="Nakit", pattern="^(Nakit|Kart|Havale|Yemek kartı)$")
    invoice_id: str = ""
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

DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
LEAVE_TYPES = ("Yıllık izin", "Raporlu", "Mazeret izni", "Ücretsiz izin", "Haftalık izin")

class LeaveEntry(Entry):
    staff_id: str = Field(min_length=1)
    date: str = Field(pattern=DATE_PATTERN)
    type: str = Field(default="Yıllık izin", pattern="^(" + "|".join(LEAVE_TYPES) + ")$")
    note: str = ""

class AdvanceEntry(Entry):
    staff_id: str = Field(min_length=1)
    date: str = Field(pattern=DATE_PATTERN)
    amount: float = Field(gt=0)
    note: str = ""

class OrderItem(BaseModel):
    inventory_id: str = ""
    name: str
    unit: str = ""
    quantity: float = 0
    unit_price: float = 0

class OrderEntry(Entry):
    supplier: str
    phone: str = ""
    channel: str = "WhatsApp"
    items: List[OrderItem] = []
    estimated_total: float = 0
    status: str = Field(default="Gönderildi", pattern="^(Gönderildi|Teslim alındı)$")
    expense_id: str = ""

class LeaveRequestIn(BaseModel):
    start: date_cls
    end: date_cls
    type: str = Field(default="Yıllık izin", pattern="^(" + "|".join(LEAVE_TYPES) + ")$")
    note: str = Field(default="", max_length=300)

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
    hourly_wage: float = 0
    phone: str = ""
    annual_leave_days: float = 14
    request_token: str = Field(default_factory=lambda: secrets.token_urlsafe(16))

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
    description: str = Field(default="", max_length=200)
    photo: Dict[str, Any] = {}

class IncomeEntry(Entry):
    date: str = Field(pattern=DATE_PATTERN)
    amount: float = Field(gt=0)
    payment: str = Field(default="Nakit", pattern="^(Nakit|Kart|Yemek kartı|Havale)$")
    category: str = Field(default="POS satış", min_length=1, max_length=40)
    note: str = Field(default="", max_length=300)

class InvoiceEntry(Entry):
    invoice_no: str = Field(default="", max_length=40)
    supplier: str = Field(min_length=1, max_length=80)
    date: str = Field(pattern=DATE_PATTERN)
    due_date: str = Field(default="", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    amount: float = Field(gt=0)
    vat_rate: float = Field(default=20, ge=0, le=100)
    category: str = Field(default="Malzeme alımı", max_length=40)
    note: str = Field(default="", max_length=300)
    status: str = Field(default="Ödenmedi", pattern="^(Ödenmedi|Ödendi)$")
    paid_at: str = ""
    paid_payment: str = ""
    expense_id: str = ""
    files: List[Dict[str, Any]] = []

class TableEntry(Entry):
    name: str = Field(min_length=1)
    seats: int = Field(default=4, ge=1)

class TipEntry(Entry):
    date: str = Field(pattern=DATE_PATTERN)
    amount: float = Field(gt=0)
    note: str = ""

class AttendanceEntry(Entry):
    staff_id: str = Field(min_length=1)
    date: str = Field(pattern=DATE_PATTERN)
    start: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    end: str = Field(default="", pattern=r"^(([01]\d|2[0-3]):[0-5]\d)?$")
    note: str = ""

class WasteEntry(Entry):
    inventory_name: str = Field(min_length=1)
    quantity: float = Field(gt=0)
    reason: str = "Bozuldu"
    note: str = ""
    inventory_id: str = ""
    unit: str = ""
    cost: float = 0

COLLECTIONS = {"sales": SalesEntry, "expenses": ExpenseEntry, "inventory": InventoryEntry, "staff": StaffEntry, "cash": CashEntry, "products": ProductEntry, "suppliers": SupplierEntry, "shifts": ShiftEntry, "leaves": LeaveEntry, "advances": AdvanceEntry, "orders": OrderEntry, "waste": WasteEntry, "tables": TableEntry, "tips": TipEntry, "attendance": AttendanceEntry, "incomes": IncomeEntry, "invoices": InvoiceEntry}

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
    waste = await list_items("waste")
    leaves = await db.leaves.find({}, {"_id": 0}).sort("date", 1).to_list(None)
    leave_requests = await db.leave_requests.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)
    advances = await db.advances.find({}, {"_id": 0}).sort("date", -1).to_list(None)
    shifts = await db.shifts.find({}, {"_id": 0}).sort([("date", 1), ("start", 1)]).to_list(None)
    today = datetime.now(TZ).date()
    week_start = datetime.combine(today - timedelta(days=6), datetime.min.time(), TZ).astimezone(timezone.utc).isoformat()
    week_sales = await list_items("sales", week_start, None) + await list_items("incomes", week_start, None)
    week_expenses = await list_items("expenses", week_start, None)
    weekly = []
    for offset in range(6, -1, -1):
        day = (today - timedelta(days=offset)).isoformat()
        weekly.append({"date": day, "revenue": _total(i for i in week_sales if local_day(i["created_at"]) == day), "expenses": _total(i for i in week_expenses if local_day(i["created_at"]) == day)})
    revenue, spent = weekly[-1]["revenue"], weekly[-1]["expenses"]
    low_stock = sum(1 for item in inventory if float(item.get("quantity", 0)) <= float(item.get("minimum", 0)))
    all_inventory = await db.raw.inventory.find({}, {"_id": 0, "id": 1, "name": 1, "unit": 1, "unit_cost": 1, "restaurant_id": 1, "created_at": 1}).sort("created_at", 1).to_list(None)
    extra = {"all_inventory": all_inventory, "tables": await db.tables.find({}, {"_id": 0}).sort("name", 1).to_list(None), "tips": await list_items("tips"),
             "attendance": await list_items("attendance", limit=300), "restaurant_id": current_rid.get(), "overhead_ratio": (await overhead_info())["ratio_pct"],
             "incomes": await list_items("incomes", limit=300), "invoices": await db.invoices.find({}, {"_id": 0}).sort("date", -1).to_list(300), "settings": await app_settings()}
    return {**extra, "revenue": revenue, "expenses": spent, "profit": revenue - spent, "low_stock": low_stock, "staff_count": len(staff), "weekly": weekly, "sales": sales, "expenses_list": expenses, "inventory": inventory, "staff": staff, "cash": cash, "products": products, "suppliers": suppliers, "shifts": shifts, "leaves": leaves, "advances": advances, "leave_requests": leave_requests, "waste": waste}

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
    incomes = await list_items("incomes", since, None, until)
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
    revenue, spent = _total(sales) + _total(incomes), _total(expenses)
    waste = await db.waste.find({"created_at": {"$gte": since, "$lt": until}}, {"_id": 0}).to_list(None)
    return {"incomes_list": incomes, "incomes_total": _total(incomes), "product_sales_total": _total(sales), "payments": payment_breakdown(sales + incomes), "waste_cost": round(sum(float(w.get("cost", 0)) for w in waste), 2), "waste_count": len(waste), "period": period, "start": begin.isoformat(), "end": (finish - timedelta(seconds=1)).isoformat(), "revenue": revenue, "expenses": spent, "profit": revenue - spent, "sales_count": len(sales) + len(incomes),
            "top_products": sorted(products.values(), key=lambda row: row["quantity"], reverse=True), "sales": sales, "expenses_list": expenses}

REC_KEYS = ("opening", "sales", "cash_sales", "expenses", "expected_closing", "actual_closing", "difference")

async def per_restaurant(period: str, start: str | None, end: str | None) -> List[Dict[str, Any]]:
    rows = []
    for r in RESTAURANTS:
        token = current_rid.set(r["id"])
        try:
            rep = await build_report(period, start, end)
            rec = await cash_reconciliation(None if period != "custom" else end)
            low = [i for i in await list_items("inventory", limit=None) if float(i.get("quantity", 0)) <= float(i.get("minimum", 0))]
        finally:
            current_rid.reset(token)
        rows.append({"id": r["id"], "name": r["name"], "revenue": rep["revenue"], "expenses": rep["expenses"], "profit": rep["profit"], "sales_count": rep["sales_count"],
                     "payments": rep["payments"], "waste_cost": rep["waste_cost"], "reconciliation": rec, "low_stock": low})
    return rows

async def full_report(period: str, start: str | None = None, end: str | None = None) -> Dict[str, Any]:
    report = await build_report(period, start, end)
    if current_rid.get() in (None, "all"):
        rows = await per_restaurant(period, start, end)
        report["restaurants"] = rows
        report["reconciliation"] = {"date": rows[0]["reconciliation"]["date"], "has_closing": all(r["reconciliation"]["has_closing"] for r in rows),
                                    **{k: round(sum(r["reconciliation"][k] for r in rows), 2) for k in REC_KEYS}}
    else:
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
        token = current_rid.set(None)
        try:
            report = await full_report("daily")
        finally:
            current_rid.reset(token)
        report["low_stock"] = [{**i, "name": f"{i['name']} ({r['name']})"} for r in report["restaurants"] for i in r["low_stock"]]
        for r in report["restaurants"]:
            to = (rest.DOCS.get(r["id"], {}).get("email") or "").strip()
            if to:
                try:
                    await asyncio.to_thread(send_restaurant_daily_email, r, day, to)
                except Exception:
                    logging.exception("restaurant daily email failed for %s", r["id"])
        await asyncio.to_thread(send_report_email, build_pdf(report), report, day)
    return await _deliver("daily", trigger, key, job)

async def send_weekly_summary(trigger: str, key: str | None = None) -> Dict[str, Any]:
    async def job(day):
        today = datetime.now(TZ).date()
        start, end = today - timedelta(days=today.weekday() + 7), today - timedelta(days=today.weekday() + 1)
        report = await build_report("custom", start.isoformat(), end.isoformat())
        await asyncio.to_thread(send_weekly_email, report, f"{start.strftime('%d.%m.%Y')} – {end.strftime('%d.%m.%Y')}")
    return await _deliver("weekly", trigger, key, job)

async def send_monthly_summary(trigger: str, key: str | None = None) -> Dict[str, Any]:
    async def job(day):
        first_this = datetime.now(TZ).date().replace(day=1)
        last = first_this - timedelta(days=1)
        first = last.replace(day=1)
        report = await build_report("custom", first.isoformat(), last.isoformat())
        pay = await build_payroll(first.strftime("%Y-%m"))
        await asyncio.to_thread(send_monthly_email, report, pay, first.strftime("%Y-%m"))
    return await _deliver("monthly", trigger, key, job)

async def notify_leave_request(staff_name: str, doc: Dict[str, Any]) -> None:
    async def job(day):
        await asyncio.to_thread(send_leave_request_email, staff_name, doc)
    if os.environ.get("GMAIL_USERNAME") and os.environ.get("GMAIL_APP_PASSWORD"):
        await _deliver("leave_request", "auto", doc["id"], job)

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

@api.get("/me")
async def me(request: Request):
    member = await current_member(request)
    rest.refresh(await db.raw.restaurants.find({}, {"_id": 0}).sort("created_at", 1).to_list(200))
    rid = member.get("restaurant_id") or rest.default_rid()
    mine = [r for r in RESTAURANTS if member["role"] == "admin" or r["id"] == rid]
    return {"user_id": member["user_id"], "email": member.get("email", ""), "role": member["role"], "restaurants": mine,
            "restaurant_id": rid, "restaurant_name": RESTAURANT_NAMES.get(rid, ""), "staff_id": member.get("staff_id", ""), **(await app_settings())}

@api.get("/users")
async def list_users():
    people = await db.users.find(IN_ENV, {"_id": 0}).to_list(1000)
    staff = await db.raw.staff.find({}, {"_id": 0, "id": 1, "name": 1, "restaurant_id": 1}).to_list(2000)
    return {"roles": ROLES, "users": [{**p, "role": effective_role(p.get("role"))} for p in people], "staff": staff}

class RoleIn(BaseModel):
    role: str

@api.patch("/users/{user_id}/role")
async def set_role(user_id: str, body: RoleIn):
    if body.role not in ROLES:
        raise HTTPException(status_code=403, detail="Not allowed")
    target = await db.users.find_one({"user_id": user_id, **IN_ENV}, {"_id": 0})
    if target is None:
        raise HTTPException(status_code=404, detail="Not found")
    if (effective_role(target.get("role")) == "admin" and body.role != "admin"
            and await db.users.count_documents({"role": "admin", **IN_ENV}) <= 1):
        raise HTTPException(status_code=409, detail="En az bir yönetici kalmalı")
    await db.users.update_one({"user_id": user_id}, {"$set": {"role": body.role}})
    return {"user_id": user_id, "role": body.role}

class AssignmentIn(BaseModel):
    restaurant_id: str
    staff_id: str = ""

@api.patch("/users/{user_id}/assignment")
async def set_assignment(user_id: str, body: AssignmentIn, request: Request):
    if body.restaurant_id not in RESTAURANT_IDS:
        raise HTTPException(status_code=422, detail="Geçersiz restoran")
    target = await db.users.find_one({"user_id": user_id, **IN_ENV}, {"_id": 0, "role": 1, "restaurant_id": 1})
    if target and target.get("role") == "manager" and target.get("restaurant_id") != body.restaurant_id:
        raise HTTPException(status_code=409, detail="Restoran müdürü, restoranın e-postasıyla bağlanır. Restoranlar bölümünden e-postayı değiştirin")
    if body.staff_id and not await db.raw.staff.find_one({"id": body.staff_id, "restaurant_id": body.restaurant_id}):
        raise HTTPException(status_code=422, detail="Personel bu restorana ait değil")
    result = await db.users.update_one({"user_id": user_id, **IN_ENV}, {"$set": {"restaurant_id": body.restaurant_id, "staff_id": body.staff_id}})
    if not result.matched_count:
        raise HTTPException(status_code=404, detail="Not found")
    await audit(request, "Atadı", "users", user_id, detail=f"{RESTAURANT_NAMES[body.restaurant_id]}{' · personel bağlandı' if body.staff_id else ''}")
    return {"user_id": user_id, **body.model_dump()}

class CountIn(BaseModel):
    quantity: float = Field(ge=0)

@api.get("/staff-view")
async def staff_view(request: Request):
    member = getattr(request.state, "member", {})
    today_start = _day_start(datetime.now(TZ).date()).astimezone(timezone.utc).isoformat()
    mine: Dict[str, float] = {}
    for sale in await db.sales.find({"created_by": member.get("email", "-"), "created_at": {"$gte": today_start}}, {"_id": 0}).to_list(None):
        mine[sale["product_name"]] = mine.get(sale["product_name"], 0) + float(sale["quantity"])
    my_today = sorted(({"product_name": k, "quantity": v} for k, v in mine.items()), key=lambda r: -r["quantity"])
    products = [{k: p.get(k) for k in ("id", "name", "category", "price", "active")} for p in await list_items("products", limit=None)]
    inventory = [{k: i.get(k) for k in ("id", "name", "quantity", "unit", "minimum")} for i in await list_items("inventory", limit=None)]
    return {"products": products, "inventory": inventory, "my_today": my_today}

@api.get("/public/menu")
async def public_menu():
    cats = await menu_groups()
    for g in cats:
        g["items"] = [{k: i[k] for k in ("name", "price", "description", "photo_url")} for i in g["items"]]
    return {"name": "Florya Dürüm Tır", "categories": cats}

async def menu_groups() -> List[Dict[str, Any]]:
    """Active products grouped by category ('kebap' and 'Kebap ' merge), in the owner's manual order."""
    order = (await db.settings.find_one({"id": "menu_order"}, {"_id": 0}) or {}).get("categories", [])
    rank = {_tr_key(c): i for i, c in enumerate(order)}
    groups: Dict[str, Dict[str, Any]] = {}
    for p in sorted(await list_items("products", limit=None), key=lambda x: (x.get("sort_order", 10**6), _tr_key(x["name"]))):
        if p.get("active", True):
            raw = (p.get("category") or "").strip() or "Menü"
            group = groups.setdefault(_tr_key(raw), {"category": ("İ" if raw[0] == "i" else raw[0].upper()) + raw[1:], "items": []})
            photo = (p.get("photo") or {}).get("id")
            group["items"].append({"id": p["id"], "name": p["name"], "price": p.get("price", 0), "description": p.get("description", ""), "photo_url": f"/api/public/photos/{photo}" if photo else ""})
    cats = sorted(groups.values(), key=lambda g: (rank.get(_tr_key(g["category"]), 10**6), _tr_key(g["category"])))
    for g in cats:
        g["cover"] = next((i["photo_url"] for i in g["items"] if i["photo_url"]), "")
        g["count"] = len(g["items"])
    return cats

class MenuOrderIn(BaseModel):
    categories: List[str] = Field(max_length=200)
    products: List[str] = Field(max_length=2000)

@api.get("/menu-order")
async def get_menu_order():
    return [{"category": g["category"], "items": [{"id": i["id"], "name": i["name"], "photo_url": i["photo_url"]} for i in g["items"]]} for g in await menu_groups()]

@api.put("/menu-order")
async def save_menu_order(body: MenuOrderIn, request: Request):
    await db.settings.update_one({"id": "menu_order"}, {"$set": {"id": "menu_order", "categories": [c.strip() for c in body.categories]}}, upsert=True)
    for i, pid in enumerate(body.products):
        await db.products.update_one({"id": pid}, {"$set": {"sort_order": i}})
    await audit(request, "Menü sırasını değiştirdi", "products", None, detail=f"{len(body.categories)} kategori")
    return {"ok": True}

class ChatIn(BaseModel):
    session_id: str = Field(min_length=8, max_length=64)
    message: str = Field(min_length=1, max_length=1000)

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

async def ai_context() -> str:
    data: Dict[str, Any] = {}
    for period, label in (("daily", "bugün"), ("weekly", "bu hafta"), ("monthly", "bu ay")):
        r = await build_report(period)
        data[label] = {k: r.get(k) for k in ("revenue", "expenses", "profit", "sales_count", "payments", "waste_cost", "start", "end")}
    month_start = _range("monthly", None, None)[0].astimezone(timezone.utc).isoformat()
    by_cat: Dict[str, float] = {}
    for e in await list_items("expenses", month_start, None):
        by_cat[e.get("category") or "Diğer"] = round(by_cat.get(e.get("category") or "Diğer", 0) + float(e.get("amount", 0)), 2)
    data["bu_ay_gider_kategorileri"] = by_cat
    data["son_gelirler"] = [{k: i.get(k) for k in ("date", "amount", "payment", "category")} for i in (await list_items("incomes", None, 40))]
    inv = await list_items("inventory", limit=None)
    data["stok"] = [{k: i.get(k) for k in ("name", "quantity", "unit", "minimum", "unit_cost")} for i in inv[:150]]
    data["kritik_stok"] = [i["name"] for i in inv if float(i.get("quantity", 0)) <= float(i.get("minimum", 0))]
    costs = await product_costs()
    data["urun_maliyetleri"] = [{k: p.get(k) for k in ("name", "category", "price", "cost", "margin", "food_cost_pct", "suggested_price", "suggested_with_overhead")} for p in costs["products"][:150]]
    data["sabit_giderler"] = costs.get("overhead")
    data["personel_sayisi"] = len(await list_items("staff", limit=None))
    return json.dumps(data, ensure_ascii=False, default=str)

@api.post("/ai/chat")
async def ai_chat(body: ChatIn, request: Request):
    member = request.state.member
    if ai.rate_limited(f"admin:{member['user_id']}", 40, 600):
        raise HTTPException(status_code=429, detail="Çok fazla soru sordunuz, birkaç dakika sonra tekrar deneyin")
    rid = current_rid.get()
    system = ai.ADMIN_PROMPT.format(today=datetime.now(TZ).strftime("%d.%m.%Y %A"), restaurant="Tüm restoranlar" if rid == "all" else RESTAURANT_NAMES.get(rid, ""), data=await ai_context())
    return StreamingResponse(ai.stream_answer(db.raw.ai_messages, body.session_id, member["user_id"], system, body.message, {"restaurant_id": rid}), media_type="text/event-stream", headers=SSE_HEADERS)

@api.get("/ai/history")
async def ai_history(session_id: str, request: Request):
    return await ai.history(db.raw.ai_messages, session_id, request.state.member["user_id"])

@api.post("/public/menu-chat")
async def menu_chat(body: ChatIn, request: Request):
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "")).split(",")[-1].strip()
    if ai.rate_limited(f"ip:{ip}", 15, 600) or ai.rate_limited("menu:all", 400, 3600):
        raise HTTPException(status_code=429, detail="Çok fazla mesaj gönderildi, lütfen biraz sonra tekrar deneyin")
    menu = await public_menu()
    data = json.dumps([{"kategori": c["category"], "urunler": [{"ad": i["name"], "fiyat": i["price"], "aciklama": i["description"]} for i in c["items"]]} for c in menu["categories"]], ensure_ascii=False)
    system = ai.MENU_PROMPT.format(name=menu["name"], data=data)
    return StreamingResponse(ai.stream_answer(db.raw.menu_chat, body.session_id, "public", system, body.message[:500]), media_type="text/event-stream", headers=SSE_HEADERS)

async def send_cash_reminder(trigger: str, key: str | None = None) -> Dict[str, Any] | None:
    last = None
    for r in RESTAURANTS:
        token = current_rid.set(r["id"])
        try:
            rec = await cash_reconciliation()
        finally:
            current_rid.reset(token)
        if rec["has_closing"] or not rec["sales"]:
            continue
        async def job(day, rec=rec, name=r["name"]):
            await asyncio.to_thread(send_cash_reminder_email, {**rec, "restaurant": name})
        last = await _deliver("cash_reminder", trigger, f"{key}:{r['id']}" if key else r["id"], job)
    return last

async def send_missing_revenue(trigger: str, key: str | None = None) -> List[str]:
    day = datetime.now(TZ).strftime("%d.%m.%Y")
    warned = []
    for r in list(RESTAURANTS):
        token = current_rid.set(r["id"])
        try:
            revenue = (await build_report("daily"))["revenue"]
        finally:
            current_rid.reset(token)
        if revenue:
            continue
        to = (rest.DOCS.get(r["id"], {}).get("email") or "").strip() or None
        async def job(_day, name=r["name"], to=to):
            await asyncio.to_thread(send_missing_revenue_email, name, day, to)
        await _deliver("missing_revenue", trigger, f"{key}:{r['id']}" if key else r["id"], job)
        warned.append(r["id"])
    return warned

@api.post("/cron/missing-revenue")
async def cron_missing_revenue(request: Request, background: BackgroundTasks):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    run_id = await accept_cron(request)
    if not run_id:
        return {"status": "duplicate"}
    background.add_task(send_missing_revenue, "cron", run_id)
    return {"status": "accepted"}

@api.post("/cron/cash-reminder")
async def cron_cash_reminder(request: Request, background: BackgroundTasks):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    run_id = await accept_cron(request)
    if not run_id:
        return {"status": "duplicate"}
    background.add_task(send_cash_reminder, "cron", run_id)
    return {"status": "accepted"}

@api.post("/inventory/{item_id}/count")
async def count_inventory(item_id: str, body: CountIn, request: Request):
    old = await db.inventory.find_one({"id": item_id}, {"_id": 0})
    if not old:
        raise HTTPException(status_code=404, detail="Malzeme bulunamadı")
    new = round(body.quantity, 3)
    await db.inventory.update_one({"id": item_id}, {"$set": {"quantity": new}})
    if new != float(old.get("quantity", 0)):
        await log_movement({**old, "quantity": new}, new - float(old.get("quantity", 0)), "Stok sayımı")
    await audit(request, "Saydı", "inventory", item_id, detail=f"{old['name']}: {float(old.get('quantity', 0)):g} → {new:g} {old.get('unit', '')}")
    return {"id": item_id, "quantity": new}

@api.get("/audit-logs")
async def audit_logs(collection: str | None = None, user_email: str | None = None, limit: int = Query(200, ge=1, le=1000)):
    query = {k: v for k, v in (("collection", collection), ("user_email", user_email)) if v}
    return await db.audit_logs.find(query, {"_id": 0}).sort("created_at", -1).to_list(limit)

@api.post("/cron/monthly-summary")
async def cron_monthly_summary(request: Request, background: BackgroundTasks):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    run_id = await accept_cron(request)
    if not run_id:
        return {"status": "duplicate"}
    background.add_task(send_monthly_summary, "cron", run_id)
    return {"status": "accepted"}

@api.post("/email/send-now")
async def email_send_now(kind: str = Query("daily", pattern="^(daily|weekly|monthly)$")):
    record = await {"weekly": send_weekly_summary, "monthly": send_monthly_summary, "daily": send_daily_report}[kind]("manual")
    if record["status"] != "sent":
        return {"status": "failed", "detail": "E-posta gönderilemedi. Gmail bilgilerini kontrol edin."}
    return {"status": "sent", "recipient": record["recipient"]}

@api.get("/email/status")
async def email_status():
    last = await db.report_deliveries.find({}, {"_id": 0}).sort("created_at", -1).to_list(5)
    return {"recipient": os.environ.get("REPORT_RECIPIENT", ""), "configured": bool(os.environ.get("GMAIL_USERNAME") and os.environ.get("GMAIL_APP_PASSWORD")), "schedule": "Her gece 23:59", "weekly_schedule": "Her pazartesi 09:00", "monthly_schedule": "Her ayın 1'i 09:00", "history": last}

@api.get("/cash/reconciliation")
async def cash_reconciliation(date: str | None = None):
    target = date or datetime.now(TZ).date().isoformat()
    since = datetime.combine(datetime.fromisoformat(target).date(), datetime.min.time(), TZ).astimezone(timezone.utc).isoformat()
    def same_day(item):
        return local_day(item["created_at"]) == target
    sales = [item for item in await list_items("sales", since, None) + await list_items("incomes", since, None) if same_day(item)]
    expenses = [item for item in await list_items("expenses", since, None) if same_day(item) and item.get("payment", "Nakit") == "Nakit"]
    cash_logs = [item for item in await list_items("cash", since, None) if same_day(item)]
    opening = float(cash_logs[-1].get("opening", 0)) if cash_logs else 0
    actual = float(cash_logs[0].get("closing", 0)) if cash_logs else 0
    sales_total, expenses_total = _total(sales), _total(expenses)
    payments = payment_breakdown(sales)
    expected = opening + payments["Nakit"] - expenses_total
    return {"date": target, "opening": opening, "sales": sales_total, "cash_sales": payments["Nakit"], "payments": payments, "expenses": expenses_total, "expected_closing": expected, "actual_closing": actual, "difference": actual - expected, "has_closing": bool(cash_logs)}

PAYMENTS = ("Nakit", "Kart", "Yemek kartı", "Havale")

def payment_breakdown(sales: List[Dict[str, Any]]) -> Dict[str, float]:
    return {p: round(sum(float(x.get("amount", 0)) for x in sales if x.get("payment", "Nakit") == p), 2) for p in PAYMENTS}

async def apply_waste(doc: Dict[str, Any], sign: int, reason: str) -> None:
    item = await db.inventory.find_one({"id": doc["inventory_id"]}, {"_id": 0}) if doc.get("inventory_id") else None
    if not item:
        key = _tr_key(doc["inventory_name"])
        item = next((i for i in await list_items("inventory", limit=None) if _tr_key(i["name"]) == key), None)
    if not item:
        raise HTTPException(status_code=422, detail="Stokta bu isimde malzeme yok")
    if sign > 0:
        doc.update(inventory_id=item["id"], inventory_name=item["name"], unit=item.get("unit", ""), cost=round(float(doc["quantity"]) * float(item.get("unit_cost", 0)), 2))
    await apply_moves([{"inventory_id": item["id"], "delta": -float(doc["quantity"])}], sign, {"id": doc["id"], "product_name": ""}, reason)

def _tr_key(value: str) -> str:
    return (value or "").replace("I", "ı").replace("İ", "i").lower().strip()

async def stock_moves(sale: Dict[str, Any]) -> List[Dict[str, Any]]:
    quantity = float(sale.get("quantity", 1))
    key = _tr_key(sale.get("product_name", ""))
    product = await db.products.find_one({"id": sale.get("product_id")}, {"_id": 0}) if sale.get("product_id") else None
    if not product and key:
        product = next((p for p in await list_items("products", limit=None) if _tr_key(p["name"]) == key), None)
    if product and product.get("recipe"):
        moves = []
        for r in product["recipe"]:
            item = await local_inventory(r["inventory_id"])
            if item:
                moves.append({"inventory_id": item["id"], "delta": -float(r["amount"]) * quantity})
        return moves
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

async def local_inventory(inventory_id: str) -> Dict[str, Any] | None:
    """Recipes are shared; map a recipe ingredient to the same-named item of the current restaurant."""
    item = await db.raw.inventory.find_one({"id": inventory_id}, {"_id": 0})
    if not item:
        return None
    if item.get("restaurant_id") == current_rid.get():
        return item
    key = _tr_key(item["name"])
    return next((i for i in await list_items("inventory", limit=None) if _tr_key(i["name"]) == key), None)

async def average_prices() -> Dict[str, float]:
    """Inventory id -> average unit cost of that ingredient name across all restaurants."""
    inventory = await db.raw.inventory.find({}, {"_id": 0}).to_list(None)
    by_name: Dict[str, List[float]] = {}
    for i in inventory:
        if float(i.get("unit_cost", 0)) > 0:
            by_name.setdefault(_tr_key(i["name"]), []).append(float(i["unit_cost"]))
    return {i["id"]: (lambda v: sum(v) / len(v) if v else 0)(by_name.get(_tr_key(i["name"]), [])) for i in inventory}

async def local_cost(product: Dict[str, Any]) -> float:
    cost = 0.0
    for r in product.get("recipe", []):
        item = await local_inventory(r["inventory_id"])
        cost += float(r["amount"]) * float((item or {}).get("unit_cost", 0))
    return round(cost, 2)

async def with_recipe_cost(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc.get("recipe"):
        return {**doc, "cost_from_recipe": False}
    prices = await average_prices()
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
        comparison = (await price_data(item))["comparison"]
        cheapest = next((c for c in comparison if c["supplier"] != "Tedarikçi belirtilmemiş"), None)
        assigned = item.get("supplier", "")
        supplier = (cheapest or {}).get("supplier") or assigned or "Tedarikçi belirtilmemiş"
        price = (cheapest or {}).get("last_price") or float(item.get("unit_cost", 0))
        assigned_price = next((c["last_price"] for c in comparison if c["supplier"] == assigned), None)
        group = groups.setdefault(supplier, {"supplier": supplier, "phone": phones.get(_tr_key(supplier), ""), "items": [], "estimated_total": 0})
        cost = round(amount * price, 2)
        group["items"].append({"inventory_id": item["id"], "name": item["name"], "unit": item.get("unit", ""), "quantity": item.get("quantity", 0), "minimum": item.get("minimum", 0), "suggested": amount, "estimated_cost": cost,
                               "unit_price": price, "assigned_supplier": assigned, "cheapest": bool(cheapest) and sum(c["supplier"] != "Tedarikçi belirtilmemiş" for c in comparison) > 1,
                               "saving": round((assigned_price - price) * amount, 2) if cheapest and assigned_price and assigned != supplier else 0})
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

def suggested_price(product: Dict[str, Any], ratio_pct: float = 0) -> float | None:
    margin = float(product.get("target_margin") or 0) or 65
    cost = float(product.get("cost", 0))
    room = 1 - margin / 100 - ratio_pct / 100
    return math.ceil(round(cost / room, 6)) if cost > 0 and room > 0.01 else None

class WizardIngredient(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    unit: str = Field(default="adet", min_length=1, max_length=20)
    unit_cost: float | None = Field(default=None, ge=0)
    amount: float = Field(gt=0)

class WizardIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    category: str = Field(default="Genel", max_length=40)
    price: float = Field(ge=0)
    target_margin: float = Field(default=65, ge=0, lt=100)
    ingredients: List[WizardIngredient] = Field(min_length=1)

async def wizard_recipe(ingredients: List[WizardIngredient]) -> tuple[List[RecipeItem], List[str]]:
    """Resolve answers to recipe rows; missing ingredients are opened in all restaurants at the given price."""
    inventory = await db.raw.inventory.find({}, {"_id": 0}).to_list(None)
    home = current_rid.get() if current_rid.get() in RESTAURANT_IDS else DEFAULT_RESTAURANT
    recipe, created = [], []
    for ing in ingredients:
        key = _tr_key(ing.name)
        same = {i.get("restaurant_id"): i for i in inventory if _tr_key(i["name"]) == key}
        price = ing.unit_cost
        if price is None:
            price = next((float(i.get("unit_cost", 0)) for i in same.values() if float(i.get("unit_cost", 0)) > 0), 0)
        for rid in RESTAURANT_IDS:
            item = same.get(rid)
            if not item:
                base = next(iter(same.values()), None)
                item = {**InventoryEntry(name=base["name"] if base else ing.name.strip(), unit=base["unit"] if base else ing.unit, unit_cost=price).model_dump(), "restaurant_id": rid}
                await db.raw.inventory.insert_one({**item})
                same[rid] = item
                created.append(f"{item['name']} ({RESTAURANT_NAMES[rid]})")
            elif price and not float(item.get("unit_cost", 0)):
                await db.raw.inventory.update_one({"id": item["id"]}, {"$set": {"unit_cost": price}})
        recipe.append(RecipeItem(inventory_id=same[home]["id"], amount=ing.amount))
    return recipe, created

@api.post("/products/wizard")
async def product_wizard(body: WizardIn, request: Request):
    if any(_tr_key(p["name"]) == _tr_key(body.name) for p in await list_items("products", limit=None)):
        raise HTTPException(status_code=409, detail=f"'{body.name}' adında bir menü ürünü zaten var")
    recipe, created = await wizard_recipe(body.ingredients)
    doc = await with_recipe_cost(ProductEntry(name=body.name.strip(), category=body.category.strip() or "Genel", price=body.price, target_margin=body.target_margin, recipe=recipe).model_dump())
    await db.products.insert_one({**doc})
    await audit(request, "Ekledi", "products", doc["id"], doc)
    return {"product": ProductEntry(**doc).model_dump(), "created_ingredients": created}

class WizardRecipeIn(BaseModel):
    price: float = Field(ge=0)
    target_margin: float = Field(default=65, ge=0, lt=100)
    ingredients: List[WizardIngredient] = Field(min_length=1)

@api.post("/products/{product_id}/wizard-recipe")
async def product_wizard_recipe(product_id: str, body: WizardRecipeIn, request: Request):
    old = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not old:
        raise HTTPException(status_code=404, detail="Ürün bulunamadı")
    recipe, created = await wizard_recipe(body.ingredients)
    doc = await with_recipe_cost({**old, "price": body.price, "target_margin": body.target_margin, "recipe": [r.model_dump() for r in recipe]})
    await db.products.replace_one({"id": product_id}, doc)
    await audit(request, "Tarif ekledi", "products", product_id, doc)
    return {"product": ProductEntry(**doc).model_dump(), "created_ingredients": created}

@api.post("/products/apply-suggested")
async def apply_suggested_prices(payload: Dict[str, List[str]], request: Request):
    ids = set(payload.get("product_ids", []))
    changed = []
    ratio = (await overhead_info())["ratio_pct"]
    for product in await list_items("products", limit=None):
        price = suggested_price(product, ratio)
        if product["id"] in ids and price and price != float(product.get("price", 0)):
            await db.products.update_one({"id": product["id"]}, {"$set": {"price": price}})
            changed.append({"id": product["id"], "name": product["name"], "old_price": product.get("price", 0), "new_price": price})
    if changed:
        await audit(request, "Toplu fiyat", "products", "", detail=", ".join(f"{c['name']} {c['old_price']:g}→{c['new_price']:g} ₺" for c in changed)[:500])
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

class CopyWeekRequest(BaseModel):
    from_start: date_cls
    to_start: date_cls

@api.post("/shifts/copy-week")
async def copy_week(req: CopyWeekRequest, request: Request):
    source_days = [(req.from_start + timedelta(days=i)).isoformat() for i in range(7)]
    offset = req.to_start - req.from_start
    source = await db.shifts.find({"date": {"$in": source_days}}, {"_id": 0}).to_list(None)
    staff_ids = {x["id"] for x in await list_items("staff", limit=None)}
    target_days = [(req.to_start + timedelta(days=i)).isoformat() for i in range(7)]
    existing = {(x["staff_id"], x["date"], x["start"]) for x in await db.shifts.find({"date": {"$in": target_days}}, {"_id": 0}).to_list(None)}
    created = 0
    for shift in source:
        new_date = (date_cls.fromisoformat(shift["date"]) + offset).isoformat()
        if shift["staff_id"] not in staff_ids or (shift["staff_id"], new_date, shift["start"]) in existing:
            continue
        doc = ShiftEntry(staff_id=shift["staff_id"], date=new_date, start=shift["start"], end=shift["end"], task=shift.get("task", "")).model_dump()
        await db.shifts.insert_one({**doc})
        existing.add((shift["staff_id"], new_date, shift["start"]))
        created += 1
    if created:
        await audit(request, "Kopyaladı", "shifts", "", detail=f"{req.from_start} haftasından {req.to_start} haftasına {created} vardiya")
    return {"created": created, "source_count": len(source)}

async def price_data(item: Dict[str, Any]) -> Dict[str, Any]:
    history = []
    async for exp in db.expenses.find({"purchases.inventory_id": item["id"]}, {"_id": 0}).sort("created_at", 1):
        for p in exp.get("purchases", []):
            if p["inventory_id"] == item["id"] and float(p.get("unit_price", 0)) > 0:
                history.append({"date": exp["created_at"], "unit_price": float(p["unit_price"]), "quantity": float(p["quantity"]),
                                "supplier": exp.get("supplier") or item.get("supplier") or "Tedarikçi belirtilmemiş"})
    suppliers: Dict[str, Dict[str, Any]] = {}
    for h in history:
        row = suppliers.setdefault(h["supplier"], {"supplier": h["supplier"], "prices": [], "quantity": 0})
        row["prices"].append(h["unit_price"])
        row["quantity"] += h["quantity"]
        row["last_price"], row["last_date"] = h["unit_price"], h["date"]
    comparison = [{"supplier": r["supplier"], "last_price": r["last_price"], "last_date": r["last_date"], "min_price": min(r["prices"]), "avg_price": round(sum(r["prices"]) / len(r["prices"]), 2),
                   "purchases": len(r["prices"]), "quantity": round(r["quantity"], 3)} for r in suppliers.values()]
    comparison.sort(key=lambda r: r["last_price"])
    return {"history": history, "comparison": comparison}

@api.get("/inventory/{item_id}/prices")
async def ingredient_prices(item_id: str):
    item = await db.inventory.find_one({"id": item_id}, {"_id": 0})
    if not item:
        raise HTTPException(status_code=404, detail="Malzeme bulunamadı")
    return {"item": {"id": item["id"], "name": item["name"], "unit": item.get("unit", ""), "unit_cost": item.get("unit_cost", 0)}, **await price_data(item)}

WEEKLY_LIMIT, OVERTIME_RATE = 45, 1.5

def shift_hours(shift: Dict[str, Any]) -> float:
    sh, sm = map(int, shift["start"].split(":"))
    eh, em = map(int, shift["end"].split(":"))
    minutes = eh * 60 + em - (sh * 60 + sm)
    return (minutes + 1440 if minutes < 0 else minutes) / 60

def split_overtime(shifts: List[Dict[str, Any]]) -> Dict[str, tuple]:
    """Per shift id -> (regular, overtime), hours beyond WEEKLY_LIMIT in each Mon–Sun week are overtime."""
    result, weeks = {}, {}
    for s in sorted(shifts, key=lambda x: (x["date"], x["start"])):
        d = date_cls.fromisoformat(s["date"])
        key = (s["staff_id"], (d - timedelta(days=d.weekday())).isoformat())
        used = weeks.get(key, 0)
        h = shift_hours(s)
        regular = max(0, min(h, WEEKLY_LIMIT - used))
        result[s["id"]] = (regular, h - regular)
        weeks[key] = used + h
    return result

async def build_payroll(month: str) -> Dict[str, Any]:
    first = date_cls.fromisoformat(f"{month}-01")
    nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    span_start, span_end = first - timedelta(days=first.weekday()), nxt + timedelta(days=6)
    span = {"date": {"$gte": span_start.isoformat(), "$lt": span_end.isoformat()}}
    planned = await db.shifts.find(span, {"_id": 0}).to_list(None)
    clocked = [a for a in await db.attendance.find(span, {"_id": 0}).to_list(None) if a.get("end")]
    real_staff = {a["staff_id"] for a in clocked}
    shifts = [s for s in planned if s["staff_id"] not in real_staff] + clocked
    split = split_overtime(shifts)
    month_range = {"$gte": first.isoformat(), "$lt": nxt.isoformat()}
    leaves = await db.leaves.find({"date": month_range}, {"_id": 0}).to_list(None)
    advances = await db.advances.find({"date": month_range}, {"_id": 0}).sort("date", 1).to_list(None)
    rows = []
    for person in await list_items("staff", limit=None):
        wage = float(person.get("hourly_wage", 0))
        mine = [s for s in shifts if s["staff_id"] == person["id"] and first.isoformat() <= s["date"] < nxt.isoformat()]
        regular = sum(split[s["id"]][0] for s in mine)
        overtime = sum(split[s["id"]][1] for s in mine)
        rows.append({"staff_id": person["id"], "name": person["name"], "task": person.get("task", ""), "hourly_wage": wage, "shift_count": len(mine),
                     "regular_hours": round(regular, 2), "overtime_hours": round(overtime, 2), "regular_pay": round(regular * wage, 2),
                     "overtime_pay": round(overtime * wage * OVERTIME_RATE, 2), "total_pay": round(regular * wage + overtime * wage * OVERTIME_RATE, 2),
                     "shifts": sorted([{**s, "hours": round(shift_hours(s), 2), "overtime": round(split[s["id"]][1], 2)} for s in mine], key=lambda x: (x["date"], x["start"]))})
        row = rows[-1]
        row["hours_source"] = "Giriş-çıkış" if person["id"] in real_staff else "Vardiya planı"
        row["leave_days"] = sum(1 for x in leaves if x["staff_id"] == person["id"] and x.get("type") != "Haftalık izin")
        row["advances"] = [a for a in advances if a["staff_id"] == person["id"]]
        row["advance_total"] = round(sum(float(a["amount"]) for a in row["advances"]), 2)
        row["net_pay"] = round(row["total_pay"] - row["advance_total"], 2)
    totals = {k: round(sum(r[k] for r in rows), 2) for k in ("regular_hours", "overtime_hours", "regular_pay", "overtime_pay", "total_pay", "advance_total", "net_pay", "leave_days")}
    return {"month": month, "weekly_limit": WEEKLY_LIMIT, "overtime_rate": OVERTIME_RATE, "rows": rows, "totals": totals}

MONTH = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")

@api.get("/payroll")
async def payroll(month: str | None = MONTH):
    return await build_payroll(month or datetime.now(TZ).strftime("%Y-%m"))

@api.get("/payroll/export")
async def payroll_export(month: str | None = MONTH):
    data = await build_payroll(month or datetime.now(TZ).strftime("%Y-%m"))
    return Response(build_payroll_excel(data), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="gokboss-pos-maas-{data["month"]}.xlsx"'})

def _purchase_total(doc: Dict[str, Any]) -> None:
    if doc.get("purchases") and not float(doc.get("amount", 0)):
        doc["amount"] = round(sum(float(p["quantity"]) * float(p.get("unit_price", 0)) for p in doc["purchases"]), 2)

async def fill_sale_cost(doc: Dict[str, Any]) -> None:
    product = await db.products.find_one({"id": doc["product_id"]}, {"_id": 0}) if doc.get("product_id") else None
    if product and product.get("recipe"):
        doc["unit_cost"] = await local_cost(product)
    elif not doc.get("unit_cost") and product:
        doc["unit_cost"] = float(product.get("cost", 0))

async def insert_sale(doc: Dict[str, Any], request: Request) -> None:
    specific_rid()
    doc["created_by"] = getattr(request.state, "member", {}).get("email", "")
    await fill_sale_cost(doc)
    doc["stock_moves"] = await stock_moves(doc)
    await apply_moves(doc["stock_moves"], 1, doc, "Satış")
    await db.sales.insert_one({**doc})
    await audit(request, "Ekledi", "sales", doc["id"], doc)

async def remove_expense(expense_id: str) -> None:
    old = await db.expenses.find_one_and_delete({"id": expense_id}, {"_id": 0})
    if old and old.get("purchases"):
        await apply_purchases(old, -1, "Teslimat geri alındı (stoktan çıkarıldı)")

async def sync_order_delivery(old: Dict[str, Any], doc: Dict[str, Any]) -> None:
    if doc["status"] == "Teslim alındı" and not old.get("expense_id"):
        purchases = [{"inventory_id": i["inventory_id"], "quantity": float(i["quantity"]), "unit_price": float(i.get("unit_price", 0))}
                     for i in doc["items"] if i.get("inventory_id") and float(i.get("quantity", 0)) > 0]
        expense = ExpenseEntry(category="Sipariş teslimi", supplier=doc["supplier"], note=f"Sipariş teslim alındı ({len(doc['items'])} kalem)", purchases=purchases).model_dump()
        if purchases:
            _purchase_total(expense)
            await apply_purchases(expense, 1, f"Teslimat · {doc['supplier']}")
        else:
            expense["amount"] = float(doc.get("estimated_total", 0))
        await db.expenses.insert_one({**expense})
        doc["expense_id"] = expense["id"]
    elif doc["status"] != "Teslim alındı" and old.get("expense_id"):
        await remove_expense(old["expense_id"])
        doc["expense_id"] = ""
    else:
        doc["expense_id"] = old.get("expense_id", "")

def leave_balance(staff: Dict[str, Any], leaves: List[Dict[str, Any]]) -> Dict[str, float]:
    year = str(datetime.now(TZ).year)
    used = sum(1 for l in leaves if l["staff_id"] == staff["id"] and l.get("type") == "Yıllık izin" and l["date"].startswith(year))
    total = float(staff.get("annual_leave_days", 14))
    return {"total": total, "used": used, "remaining": total - used}

async def staff_by_token(token: str) -> Dict[str, Any]:
    staff = await db.staff.find_one({"request_token": token}, {"_id": 0}) if len(token) >= 16 else None
    if not staff:
        raise HTTPException(status_code=404, detail="Geçersiz veya süresi dolmuş link")
    return staff

@api.get("/public/leave/{token}")
async def public_leave_info(token: str):
    staff = await staff_by_token(token)
    leaves = await db.leaves.find({"staff_id": staff["id"]}, {"_id": 0}).to_list(None)
    requests = await db.leave_requests.find({"staff_id": staff["id"]}, {"_id": 0, "staff_id": 0}).sort("created_at", -1).to_list(20)
    return {"name": staff["name"], "balance": leave_balance(staff, leaves), "requests": requests, "types": LEAVE_TYPES}

@api.post("/public/leave/{token}")
async def public_leave_request(token: str, body: LeaveRequestIn, background: BackgroundTasks):
    staff = await staff_by_token(token)
    if body.end < body.start:
        raise HTTPException(status_code=422, detail="Bitiş tarihi başlangıçtan önce olamaz")
    if (body.end - body.start).days > 30:
        raise HTTPException(status_code=422, detail="Tek talepte en fazla 31 gün seçilebilir")
    if body.start < datetime.now(TZ).date() - timedelta(days=7):
        raise HTTPException(status_code=422, detail="Geçmiş tarihler için talep gönderilemez")
    if await db.leave_requests.count_documents({"staff_id": staff["id"], "status": "Bekliyor"}) >= 10:
        raise HTTPException(status_code=429, detail="Çok fazla bekleyen talebiniz var")
    doc = {"id": str(uuid.uuid4()), "restaurant_id": staff.get("restaurant_id") or DEFAULT_RESTAURANT, "staff_id": staff["id"], "start": body.start.isoformat(), "end": body.end.isoformat(), "days": (body.end - body.start).days + 1,
           "type": body.type, "note": body.note, "status": "Bekliyor", "created_at": datetime.now(timezone.utc).isoformat()}
    await db.leave_requests.insert_one({**doc})
    background.add_task(notify_leave_request, staff["name"], doc)
    return {k: v for k, v in doc.items() if k not in ("staff_id", "restaurant_id")}

@api.post("/staff/{staff_id}/request-link")
async def staff_request_link(staff_id: str, regenerate: bool = False):
    staff = await db.staff.find_one({"id": staff_id}, {"_id": 0})
    if not staff:
        raise HTTPException(status_code=404, detail="Personel bulunamadı")
    token = staff.get("request_token")
    if regenerate or not token:
        token = secrets.token_urlsafe(16)
        await db.staff.update_one({"id": staff_id}, {"$set": {"request_token": token}})
    return {"token": token}

@api.post("/leave-requests/{request_id}/{decision}")
async def decide_leave_request(request_id: str, decision: str, request: Request):
    if decision not in ("approve", "reject"):
        raise HTTPException(status_code=404, detail="Geçersiz işlem")
    req = await db.leave_requests.find_one({"id": request_id, "status": "Bekliyor"}, {"_id": 0})
    if not req:
        raise HTTPException(status_code=404, detail="Bekleyen talep bulunamadı")
    created = 0
    if decision == "approve":
        day, end = date_cls.fromisoformat(req["start"]), date_cls.fromisoformat(req["end"])
        while day <= end:
            if not await db.leaves.find_one({"staff_id": req["staff_id"], "date": day.isoformat()}):
                await db.leaves.insert_one({**LeaveEntry(staff_id=req["staff_id"], date=day.isoformat(), type=req["type"], note=req.get("note") or "İzin talebi").model_dump(), "restaurant_id": req.get("restaurant_id") or DEFAULT_RESTAURANT})
                created += 1
            day += timedelta(days=1)
    status = "Onaylandı" if decision == "approve" else "Reddedildi"
    await db.leave_requests.update_one({"id": request_id}, {"$set": {"status": status, "decided_at": datetime.now(timezone.utc).isoformat()}})
    await audit(request, "Onayladı" if decision == "approve" else "Reddetti", "leave_requests", request_id, detail=f"İzin talebi {req['start']}–{req['end']} ({req['type']})")
    return {"status": status, "created": created}

@api.get("/payroll/{staff_id}/slip")
async def payroll_slip(staff_id: str, month: str | None = MONTH):
    data = await build_payroll(month or datetime.now(TZ).strftime("%Y-%m"))
    row = next((r for r in data["rows"] if r["staff_id"] == staff_id), None)
    if not row:
        raise HTTPException(status_code=404, detail="Personel bulunamadı")
    name = re.sub(r"[^A-Za-z0-9]+", "-", row["name"].translate(str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU"))).strip("-").lower() or "personel"
    return Response(build_payslip_pdf(row, data), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="bordro-{name}-{data["month"]}.pdf"'})

async def validate_attendance(doc: Dict[str, Any]) -> None:
    if not await db.staff.find_one({"id": doc["staff_id"]}):
        raise HTTPException(status_code=422, detail="Personel bu restoranda bulunamadı")
    if doc.get("end") and shift_hours(doc) > 16:
        raise HTTPException(status_code=422, detail="Çıkış saati girişten önce görünüyor (16 saatten uzun mesai kabul edilmez)")

def _now_hm() -> str:
    return datetime.now(TZ).strftime("%H:%M")

OPEN_ORDER = {"$in": ["Açık", "Kapanıyor"]}

def _order_total(items: List[Dict[str, Any]]) -> float:
    return round(sum(float(i["quantity"]) * float(i["unit_price"]) for i in items), 2)

def _pending_sum(pending: List[Dict[str, Any]]) -> float:
    return round(sum(float(p["amount"]) for p in pending), 2)

async def table_view_rows() -> List[Dict[str, Any]]:
    tables = await db.tables.find({}, {"_id": 0}).sort("name", 1).to_list(None)
    orders = {o["table_id"]: o for o in await db.table_orders.find({"status": OPEN_ORDER}, {"_id": 0}).to_list(None)}
    ready: Dict[str, int] = {}
    for t in await db.kitchen_tickets.find({"status": "Hazır"}, {"_id": 0, "table_id": 1}).to_list(None):
        ready[t["table_id"]] = ready.get(t["table_id"], 0) + 1
    return [{**t, "order": orders.get(t["id"]), "ready_count": ready.get(t["id"], 0) if t["id"] in orders else 0} for t in tables]

@api.get("/tables-view")
async def tables_view():
    products = [{k: p.get(k) for k in ("id", "name", "category", "price", "active")} for p in await list_items("products", limit=None) if p.get("active", True)]
    return {"tables": await table_view_rows(), "products": sorted(products, key=lambda p: (p["category"] or "", p["name"]))}

class TableItemIn(BaseModel):
    product_id: str
    quantity: float

class PayItem(BaseModel):
    product_id: str
    quantity: float = Field(gt=0)

class TablePayIn(BaseModel):
    payment: str = Field(default="Nakit", pattern="^(Nakit|Kart|Yemek kartı)$")
    tip: float = Field(default=0, ge=0)
    amount: float | None = Field(default=None, gt=0)
    items: List[PayItem] = []

async def _table(table_id: str) -> Dict[str, Any]:
    table = await db.tables.find_one({"id": table_id}, {"_id": 0})
    if not table:
        raise HTTPException(status_code=404, detail="Masa bulunamadı")
    return table

async def kitchen_add(table: Dict[str, Any], product: Dict[str, Any], quantity: float) -> None:
    ticket = await db.kitchen_tickets.find_one({"table_id": table["id"], "status": "Yeni"}, {"_id": 0})
    if not ticket:
        if quantity <= 0:
            return
        ticket = {"id": str(uuid.uuid4()), "table_id": table["id"], "table_name": table["name"], "status": "Yeni", "items": [], "created_at": datetime.now(timezone.utc).isoformat()}
        await db.kitchen_tickets.insert_one({**ticket})
    items = ticket["items"]
    row = next((i for i in items if i["product_id"] == product["id"]), None)
    if row:
        row["quantity"] = round(row["quantity"] + quantity, 3)
    elif quantity > 0:
        items.append({"product_id": product["id"], "product_name": product["name"], "quantity": quantity})
    items = [i for i in items if i["quantity"] > 0]
    if items:
        await db.kitchen_tickets.update_one({"id": ticket["id"]}, {"$set": {"items": items, "updated_at": datetime.now(timezone.utc).isoformat()}})
    else:
        await db.kitchen_tickets.delete_many({"id": ticket["id"]})

@api.post("/tables/{table_id}/items")
async def table_add_item(table_id: str, body: TableItemIn, request: Request):
    table = await _table(table_id)
    if not body.quantity:
        raise HTTPException(status_code=422, detail="Miktar 0 olamaz")
    product = await db.products.find_one({"id": body.product_id}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=422, detail="Menü ürünü bulunamadı")
    order = await db.table_orders.find_one({"table_id": table_id, "status": "Açık"}, {"_id": 0})
    if not order:
        if body.quantity < 0:
            raise HTTPException(status_code=422, detail="Masada açık hesap yok")
        if await db.table_orders.find_one({"table_id": table_id, "status": "Kapanıyor"}):
            raise HTTPException(status_code=409, detail="Masada ödeme alınıyor, birazdan tekrar deneyin")
        order = {"id": str(uuid.uuid4()), "table_id": table_id, "table_name": table["name"], "status": "Açık", "items": [], "total": 0, "pending": [], "paid": [],
                 "opened_by": getattr(request.state, "member", {}).get("email", ""), "opened_at": datetime.now(timezone.utc).isoformat(), "created_at": datetime.now(timezone.utc).isoformat()}
        await db.table_orders.insert_one({**order})
    items = order["items"]
    row = next((i for i in items if i["product_id"] == product["id"]), None)
    if row and row["quantity"] + body.quantity < 0:
        raise HTTPException(status_code=422, detail="Hesaptaki miktardan fazla çıkarılamaz")
    if row:
        row["quantity"] = round(row["quantity"] + body.quantity, 3)
    elif body.quantity > 0:
        items.append({"product_id": product["id"], "product_name": product["name"], "unit_price": float(product.get("price", 0)), "quantity": body.quantity})
    else:
        raise HTTPException(status_code=422, detail="Ürün hesapta yok")
    items = [i for i in items if i["quantity"] > 0]
    total = _order_total(items)
    if total < _pending_sum(order.get("pending", [])) - 0.01:
        raise HTTPException(status_code=422, detail="Alınan kısmi ödemeler hesaptan fazla olamaz; önce ödemeyi kaldırın")
    await db.table_orders.update_one({"id": order["id"]}, {"$set": {"items": items, "total": total}})
    await kitchen_add(table, product, body.quantity)
    return {**order, "items": items, "total": total}

def _sale_doc(item: Dict[str, Any], quantity: float, amount: float, payment: str, table: Dict[str, Any], split: bool = False) -> Dict[str, Any]:
    return SalesEntry(product_id=item["product_id"], product_name=item["product_name"], quantity=round(quantity, 4), unit_price=item["unit_price"], channel="Salon",
                      payment=payment, amount=round(amount, 2), note=f"Masa {table['name']}{' · bölünmüş hesap' if split else ''}").model_dump()

async def _save_tip(amount: float, table: Dict[str, Any], payment: str) -> str:
    if amount <= 0:
        return ""
    tip = TipEntry(date=datetime.now(TZ).date().isoformat(), amount=amount, note=f"Masa {table['name']} · {payment}").model_dump()
    await db.tips.insert_one({**tip})
    return tip["id"]

async def _pay(order: Dict[str, Any], table: Dict[str, Any], body: TablePayIn, request: Request) -> Dict[str, Any]:
    items, pending, paid = order["items"], order.get("pending", []), order.get("paid", [])
    now = datetime.now(timezone.utc).isoformat()
    async def save(status="Kapanıyor"):
        await db.table_orders.update_one({"id": order["id"]}, {"$set": {"items": items, "total": _order_total(items), "pending": pending, "paid": paid, "status": status}})
    if not items:
        raise HTTPException(status_code=422, detail="Masada ödenecek ürün yok")
    if body.items:
        selected = []
        for pi in body.items:
            row = next((i for i in items if i["product_id"] == pi.product_id), None)
            if not row or pi.quantity > row["quantity"] + 1e-9:
                raise HTTPException(status_code=422, detail="Seçilen ürün miktarı hesapta yok")
            selected.append((row, pi.quantity))
        amount = round(sum(q * r["unit_price"] for r, q in selected), 2)
        if _order_total(items) - amount < _pending_sum(pending) - 0.01:
            raise HTTPException(status_code=422, detail="Kalan hesap, alınmış kısmi ödemelerden az kalıyor; önce o ödemeleri kaldırın")
        for row, q in selected:
            await insert_sale(_sale_doc(row, q, q * row["unit_price"], body.payment, table), request)
            row["quantity"] = round(row["quantity"] - q, 4)
            items = [i for i in items if i["quantity"] > 1e-9]
            await save()
        paid.append({"id": str(uuid.uuid4()), "kind": "Ürün", "payment": body.payment, "amount": amount, "tip": body.tip, "at": now,
                     "items": [{"product_name": r["product_name"], "quantity": q} for r, q in selected], "tip_id": await _save_tip(body.tip, table, body.payment)})
    else:
        left = round(_order_total(items) - _pending_sum(pending), 2)
        amount = round(body.amount if body.amount is not None else left, 2)
        if amount <= 0 or amount > left + 0.01:
            raise HTTPException(status_code=422, detail=f"En fazla {left:g} ₺ ödeme alınabilir")
        pending.append({"id": str(uuid.uuid4()), "kind": "Tutar", "payment": body.payment, "amount": min(amount, left), "tip": body.tip, "at": now, "tip_id": await _save_tip(body.tip, table, body.payment)})
    total = _order_total(items)
    if items and _pending_sum(pending) >= total - 0.01:
        await save()
        for row in items:
            for p in pending:
                share = p["amount"] / total
                await insert_sale(_sale_doc(row, row["quantity"] * share, row["quantity"] * row["unit_price"] * share, p["payment"], table, len(pending) > 1), request)
        paid.extend(pending)
        items, pending = [], []
    closed = not items
    await db.table_orders.update_one({"id": order["id"]}, {"$set": {"items": items, "total": _order_total(items), "pending": pending, "paid": paid,
                                     "status": "Kapandı" if closed else "Açık", **({"closed_at": now} if closed else {})}})
    await audit(request, "Hesap kapattı" if closed else "Ödeme aldı", "tables", table["id"], detail=f"Masa {table['name']} · {paid[-1]['amount'] if closed or body.items else pending[-1]['amount']:g} ₺ · {body.payment}{f' · bahşiş {body.tip:g} ₺' if body.tip else ''}")
    return {"ok": True, "closed": closed, "remaining": round(_order_total(items) - _pending_sum(pending), 2)}

@api.post("/tables/{table_id}/pay")
async def table_pay(table_id: str, body: TablePayIn, request: Request):
    table = await _table(table_id)
    order = await db.table_orders.find_one_and_update({"table_id": table_id, "status": "Açık"}, {"$set": {"status": "Kapanıyor"}}, projection={"_id": 0})
    if not order:
        raise HTTPException(status_code=422, detail="Masada açık hesap yok")
    try:
        return await _pay(order, table, body, request)
    finally:
        await db.table_orders.update_one({"id": order["id"], "status": "Kapanıyor"}, {"$set": {"status": "Açık"}})

class TableCloseIn(BaseModel):
    payment: str = Field(default="Nakit", pattern="^(Nakit|Kart|Yemek kartı)$")
    tip: float = Field(default=0, ge=0)

@api.post("/tables/{table_id}/close")
async def table_close(table_id: str, body: TableCloseIn, request: Request):
    return await table_pay(table_id, TablePayIn(payment=body.payment, tip=body.tip), request)

@api.post("/tables/{table_id}/pending/{payment_id}/remove")
async def table_remove_pending(table_id: str, payment_id: str, request: Request):
    order = await db.table_orders.find_one({"table_id": table_id, "status": "Açık"}, {"_id": 0})
    payment = next((p for p in (order or {}).get("pending", []) if p["id"] == payment_id), None)
    if not payment:
        raise HTTPException(status_code=404, detail="Bekleyen ödeme bulunamadı")
    await db.table_orders.update_one({"id": order["id"]}, {"$pull": {"pending": {"id": payment_id}}})
    if payment.get("tip_id"):
        await db.tips.delete_many({"id": payment["tip_id"]})
    await audit(request, "Ödeme kaldırdı", "tables", table_id, detail=f"Masa {order['table_name']} · {payment['amount']:g} ₺ {payment['payment']}")
    return {"ok": True}

@api.post("/tables/{table_id}/cancel")
async def table_cancel(table_id: str, request: Request):
    table = await _table(table_id)
    order = await db.table_orders.find_one({"table_id": table_id, "status": "Açık"}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Masada açık hesap yok")
    if order.get("pending") or order.get("paid"):
        raise HTTPException(status_code=409, detail="Bu hesapta ödeme alınmış; iptal yerine kalan tutarı tahsil edin veya bekleyen ödemeleri kaldırın")
    await db.table_orders.delete_many({"id": order["id"]})
    await db.kitchen_tickets.delete_many({"table_id": table_id, "status": {"$in": ["Yeni", "Hazırlanıyor"]}})
    await audit(request, "Hesap iptal", "tables", table_id, detail=f"Masa {table['name']} · {order['total']:g} ₺")
    return {"ok": True}

KITCHEN_FLOW = ("Yeni", "Hazırlanıyor", "Hazır", "Teslim edildi")

class KitchenStatusIn(BaseModel):
    status: str = Field(pattern="^(Hazırlanıyor|Hazır|Teslim edildi)$")

@api.get("/kitchen")
async def kitchen():
    return await db.kitchen_tickets.find({"status": {"$in": list(KITCHEN_FLOW[:3])}}, {"_id": 0}).sort("created_at", 1).to_list(200)

@api.post("/kitchen/{ticket_id}/status")
async def kitchen_status(ticket_id: str, body: KitchenStatusIn, request: Request):
    ticket = await db.kitchen_tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not ticket:
        raise HTTPException(status_code=404, detail="Sipariş fişi bulunamadı")
    now = datetime.now(timezone.utc).isoformat()
    await db.kitchen_tickets.update_one({"id": ticket_id}, {"$set": {"status": body.status, f"{'ready' if body.status == 'Hazır' else 'started' if body.status == 'Hazırlanıyor' else 'served'}_at": now}})
    if body.status != "Hazırlanıyor":
        await audit(request, body.status, "kitchen", ticket_id, detail=f"Masa {ticket['table_name']} · " + ", ".join(f"{i['quantity']:g}× {i['product_name']}" for i in ticket["items"])[:300])
    return {"id": ticket_id, "status": body.status}

class TransferItem(BaseModel):
    inventory_id: str
    quantity: float = Field(gt=0)

class TransferIn(BaseModel):
    to_restaurant: str
    items: List[TransferItem] = Field(min_length=1)
    note: str = Field(default="", max_length=300)

async def _move_in(rid: str, source: Dict[str, Any], quantity: float, ref: Dict[str, Any], reason: str) -> Dict[str, Any]:
    token = current_rid.set(rid)
    try:
        key = _tr_key(source["name"])
        target = next((i for i in await list_items("inventory", limit=None) if _tr_key(i["name"]) == key), None)
        if not target:
            target = InventoryEntry(name=source["name"], unit=source.get("unit", "adet"), minimum=0, unit_cost=source.get("unit_cost", 0),
                                    target=0, supplier=source.get("supplier", "")).model_dump()
            await db.inventory.insert_one({**target})
        await apply_moves([{"inventory_id": target["id"], "delta": quantity}], 1, ref, reason)
        return target
    finally:
        current_rid.reset(token)

@api.get("/stock-transfers")
async def stock_transfers():
    rid = current_rid.get()
    query = {} if rid in (None, "all") else {"$or": [{"from_restaurant": rid}, {"to_restaurant": rid}]}
    return await db.stock_transfers.find(query, {"_id": 0}).sort("created_at", -1).to_list(100)

@api.post("/stock-transfers")
async def create_stock_transfer(body: TransferIn, request: Request):
    src = specific_rid()
    if body.to_restaurant not in RESTAURANT_IDS or body.to_restaurant == src:
        raise HTTPException(status_code=422, detail="Farklı bir hedef restoran seçin")
    wanted: Dict[str, float] = {}
    for it in body.items:
        wanted[it.inventory_id] = wanted.get(it.inventory_id, 0) + it.quantity
    sources = {}
    for inv_id, q in wanted.items():
        item = await db.inventory.find_one({"id": inv_id}, {"_id": 0})
        if not item:
            raise HTTPException(status_code=422, detail="Malzeme bu restoranın stoğunda yok")
        if q > float(item.get("quantity", 0)) + 1e-9:
            raise HTTPException(status_code=422, detail=f"{item['name']}: stokta yalnızca {float(item.get('quantity', 0)):g} {item.get('unit', '')} var")
        sources[inv_id] = item
    doc = {"id": str(uuid.uuid4()), "from_restaurant": src, "to_restaurant": body.to_restaurant, "from_name": RESTAURANT_NAMES[src], "to_name": RESTAURANT_NAMES[body.to_restaurant],
           "note": body.note, "items": [], "created_by": getattr(request.state, "member", {}).get("email", ""), "created_at": datetime.now(timezone.utc).isoformat()}
    ref = {"id": doc["id"], "product_name": ""}
    token = current_rid.set(body.to_restaurant)
    try:
        existing = {i["id"] for i in await list_items("inventory", limit=None)}
    finally:
        current_rid.reset(token)
    for inv_id, q in wanted.items():
        item = sources[inv_id]
        await apply_moves([{"inventory_id": inv_id, "delta": -q}], 1, ref, f"Transfer → {doc['to_name']}")
        target = await _move_in(body.to_restaurant, item, q, ref, f"Transfer ← {doc['from_name']}")
        doc["items"].append({"name": item["name"], "unit": item.get("unit", ""), "quantity": q, "unit_cost": float(item.get("unit_cost", 0)), "from_id": inv_id, "to_id": target["id"], "created": target["id"] not in existing})
    doc["value"] = round(sum(i["quantity"] * i["unit_cost"] for i in doc["items"]), 2)
    await db.stock_transfers.insert_one({**doc})
    await recompute_product_costs()
    await audit(request, "Transfer", "stock_transfers", doc["id"], detail=f"{doc['from_name']} → {doc['to_name']}: " + ", ".join(f"{i['quantity']:g} {i['unit']} {i['name']}" for i in doc["items"])[:400])
    return doc

@api.delete("/stock-transfers/{transfer_id}")
async def delete_stock_transfer(transfer_id: str, request: Request):
    src = specific_rid()
    doc = await db.stock_transfers.find_one({"id": transfer_id, "from_restaurant": src}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Transfer bulunamadı (yalnızca gönderen restoran geri alabilir)")
    token = current_rid.set(doc["to_restaurant"])
    try:
        for i in doc["items"]:
            target = await db.inventory.find_one({"id": i["to_id"]}, {"_id": 0})
            if not target or float(target.get("quantity", 0)) + 1e-9 < i["quantity"]:
                raise HTTPException(status_code=409, detail=f"{doc['to_name']} stoğunda {i['name']} yetersiz; transfer geri alınamaz")
        ref = {"id": doc["id"], "product_name": ""}
        await apply_moves([{"inventory_id": i["to_id"], "delta": -i["quantity"]} for i in doc["items"]], 1, ref, f"Transfer geri alındı → {doc['from_name']}")
        for i in doc["items"]:
            if i.get("created"):
                await db.inventory.delete_many({"id": i["to_id"], "quantity": {"$lte": 1e-9}})
    finally:
        current_rid.reset(token)
    await apply_moves([{"inventory_id": i["from_id"], "delta": i["quantity"]} for i in doc["items"]], 1, {"id": doc["id"], "product_name": ""}, f"Transfer geri alındı ← {doc['to_name']}")
    await db.stock_transfers.delete_many({"id": transfer_id})
    await audit(request, "Transfer geri aldı", "stock_transfers", transfer_id, detail=f"{doc['from_name']} → {doc['to_name']}")
    return {"ok": True}

@api.get("/tips/distribution")
async def tips_distribution(date: str = Query(None, pattern=DATE_PATTERN)):
    day = date or datetime.now(TZ).date().isoformat()
    tips = await db.tips.find({"date": day}, {"_id": 0}).to_list(None)
    total = round(sum(float(t["amount"]) for t in tips), 2)
    clocked = [a for a in await db.attendance.find({"date": day}, {"_id": 0}).to_list(None) if a.get("end")]
    real = {a["staff_id"] for a in clocked}
    entries = clocked + [s for s in await db.shifts.find({"date": day}, {"_id": 0}).to_list(None) if s["staff_id"] not in real]
    hours: Dict[str, float] = {}
    for e in entries:
        hours[e["staff_id"]] = hours.get(e["staff_id"], 0) + shift_hours(e)
    names = {p["id"]: p["name"] for p in await list_items("staff", limit=None)}
    hours = {k: v for k, v in hours.items() if k in names}
    all_hours = sum(hours.values())
    rows = [{"staff_id": k, "name": names[k], "hours": round(v, 2), "source": "Giriş-çıkış" if k in real else "Vardiya planı",
             "share": round(total * v / all_hours, 2) if all_hours else 0} for k, v in sorted(hours.items(), key=lambda x: -x[1])]
    return {"date": day, "total": total, "tips": tips, "total_hours": round(all_hours, 2), "rows": rows}

async def _my_staff(request: Request) -> Dict[str, Any]:
    member = getattr(request.state, "member", {})
    staff = await db.staff.find_one({"id": member.get("staff_id")}, {"_id": 0}) if member.get("staff_id") else None
    if not staff:
        raise HTTPException(status_code=409, detail="Hesabınız bir personel kaydına bağlı değil. Yöneticinizden Kullanıcılar sayfasından bağlamasını isteyin.")
    return staff

@api.get("/attendance/me")
async def attendance_me(request: Request):
    member = getattr(request.state, "member", {})
    staff = await db.staff.find_one({"id": member.get("staff_id")}, {"_id": 0}) if member.get("staff_id") else None
    if not staff:
        return {"linked": False}
    open_rec = await db.attendance.find_one({"staff_id": staff["id"], "end": ""}, {"_id": 0}, sort=[("created_at", -1)])
    today = await db.attendance.find({"staff_id": staff["id"], "date": datetime.now(TZ).date().isoformat()}, {"_id": 0}).sort("created_at", 1).to_list(None)
    return {"linked": True, "name": staff["name"], "open": open_rec, "today": today, "today_hours": round(sum(shift_hours(a) for a in today if a.get("end")), 2)}

@api.post("/attendance/clock")
async def attendance_clock(request: Request):
    staff = await _my_staff(request)
    open_rec = await db.attendance.find_one({"staff_id": staff["id"], "end": ""}, {"_id": 0}, sort=[("created_at", -1)])
    if open_rec:
        await db.attendance.update_one({"id": open_rec["id"]}, {"$set": {"end": _now_hm()}})
        await audit(request, "Çıkış yaptı", "attendance", open_rec["id"], detail=f"{staff['name']} · {open_rec['start']}–{_now_hm()}")
        return {"status": "out", "start": open_rec["start"], "end": _now_hm()}
    doc = AttendanceEntry(staff_id=staff["id"], date=datetime.now(TZ).date().isoformat(), start=_now_hm()).model_dump()
    await db.attendance.insert_one({**doc, "restaurant_id": staff["restaurant_id"]})
    await audit(request, "Giriş yaptı", "attendance", doc["id"], detail=f"{staff['name']} · {doc['start']}")
    return {"status": "in", "start": doc["start"]}

@api.get("/restaurants/summary")
async def restaurants_summary(request: Request):
    member = request.state.member
    if member["role"] == "manager":
        return []
    opened = rest.unlocked(member["user_id"], request.headers.get("x-restaurant-key"))
    rows = []
    for r in RESTAURANTS:
        if r["has_pin"] and r["id"] not in opened:
            rows.append({**r, "locked": True})
            continue
        token = current_rid.set(r["id"])
        try:
            today, month = await build_report("daily"), await build_report("monthly")
            low = sum(1 for i in await list_items("inventory", limit=None) if float(i.get("quantity", 0)) <= float(i.get("minimum", 0)))
            open_tables = await db.table_orders.count_documents({"status": "Açık"})
        finally:
            current_rid.reset(token)
        rows.append({**r, "today_revenue": today["revenue"], "today_expenses": today["expenses"], "today_profit": today["profit"], "today_sales": today["sales_count"],
                     "month_revenue": month["revenue"], "month_profit": month["profit"], "low_stock": low, "open_tables": open_tables})
    return rows

PIN_RE = r"\d{4,6}"
TR_SLUG = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")

class RestaurantIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    email: str = Field(default="", max_length=120)
    manager_name: str = Field(default="", max_length=60)
    manager_phone: str = Field(default="", max_length=25)
    pin: str = Field(default="", max_length=6)

class RestaurantPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    email: str | None = Field(default=None, max_length=120)
    manager_name: str | None = Field(default=None, max_length=60)
    manager_phone: str | None = Field(default=None, max_length=25)
    pin: str | None = Field(default=None, max_length=6)

class UnlockIn(BaseModel):
    pins: Dict[str, str]

def _public_restaurant(d: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": d["id"], "name": d["name"], "email": d.get("email", ""), "has_pin": bool(d.get("pin_hash")), "archived": bool(d.get("archived")), "created_at": d.get("created_at", ""),
            "logo_id": d.get("logo_id", ""), "cover_id": d.get("cover_id", ""), "manager_name": d.get("manager_name", ""), "manager_phone": d.get("manager_phone", "")}

async def _check_email(email: str, rid: str | None) -> str:
    email = email.strip().lower()
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(status_code=422, detail="Geçerli bir e-posta yazın")
    if email and any(d["id"] != rid and (d.get("email") or "").lower() == email for d in rest.DOCS.values()):
        raise HTTPException(status_code=409, detail="Bu e-posta başka bir restorana tanımlı")
    return email

def _phone(phone: str) -> str:
    phone = phone.strip()
    if phone and len(re.sub(r"\D", "", phone)) < 10:
        raise HTTPException(status_code=422, detail="Telefon numarası eksik görünüyor (örn. 0532 123 45 67)")
    return phone

def _pin_hash(pin: str) -> str:
    if pin and not re.fullmatch(PIN_RE, pin):
        raise HTTPException(status_code=422, detail="Şifre 4-6 haneli rakam olmalı")
    return rest.hash_pin(pin) if pin else ""

async def _link_email(rid: str, old: str, new: str) -> None:
    if old and old != new:
        await db.users.update_many({"role": "manager", "restaurant_id": rid, "email": {"$regex": f"^{re.escape(old)}$", "$options": "i"}}, {"$set": {"role": "member"}})
    if new:
        await db.users.update_many({"role": {"$ne": "admin"}, "email": {"$regex": f"^{re.escape(new)}$", "$options": "i"}}, {"$set": {"role": "manager", "restaurant_id": rid, "staff_id": ""}})

@api.get("/restaurants/manage")
async def manage_restaurants():
    return [_public_restaurant(d) for d in rest.DOCS.values()]

@api.post("/restaurants/manage")
async def create_restaurant(body: RestaurantIn, request: Request):
    email = await _check_email(body.email, None)
    base = re.sub(r"[^a-z0-9]+", "-", body.name.strip().translate(TR_SLUG).lower()).strip("-") or "restoran"
    rid, n = base, 2
    while rid in rest.DOCS:
        rid, n = f"{base}-{n}", n + 1
    doc = {"id": rid, "name": body.name.strip(), "email": email, "manager_name": body.manager_name.strip(), "manager_phone": _phone(body.manager_phone), "pin_hash": _pin_hash(body.pin), "archived": False, "created_at": datetime.now(timezone.utc).isoformat()}
    await db.raw.restaurants.insert_one({**doc})
    await _link_email(rid, "", email)
    await audit(request, "Restoran ekledi", "restaurants", rid, detail=doc["name"])
    return _public_restaurant(doc)

@api.patch("/restaurants/manage/{rid}")
async def update_restaurant(rid: str, body: RestaurantPatch, request: Request):
    old = rest.DOCS.get(rid)
    if not old:
        raise HTTPException(status_code=404, detail="Restoran bulunamadı")
    changes: Dict[str, Any] = {}
    if body.name is not None:
        changes["name"] = body.name.strip()
    if body.email is not None:
        changes["email"] = await _check_email(body.email, rid)
    if body.pin is not None:
        changes["pin_hash"] = _pin_hash(body.pin)
    if body.manager_name is not None:
        changes["manager_name"] = body.manager_name.strip()
    if body.manager_phone is not None:
        changes["manager_phone"] = _phone(body.manager_phone)
    await db.raw.restaurants.update_one({"id": rid}, {"$set": changes})
    if "email" in changes:
        await _link_email(rid, (old.get("email") or "").lower(), changes["email"])
    await audit(request, "Restoranı düzenledi", "restaurants", rid, detail=f"{changes.get('name', old['name'])}{' · şifre değişti' if 'pin_hash' in changes else ''}")
    return _public_restaurant({**old, **changes})

@api.post("/restaurants/manage/{rid}/archive")
async def archive_restaurant(rid: str, request: Request):
    if rid not in RESTAURANT_IDS:
        raise HTTPException(status_code=404, detail="Restoran bulunamadı")
    if len(RESTAURANT_IDS) <= 1:
        raise HTTPException(status_code=409, detail="En az bir aktif restoran kalmalı")
    await db.raw.restaurants.update_one({"id": rid}, {"$set": {"archived": True}})
    await audit(request, "Restoranı arşivledi", "restaurants", rid, detail=RESTAURANT_NAMES[rid])
    return {"id": rid, "archived": True}

@api.post("/restaurants/manage/{rid}/restore")
async def restore_restaurant(rid: str, request: Request):
    if rid not in rest.DOCS:
        raise HTTPException(status_code=404, detail="Restoran bulunamadı")
    await db.raw.restaurants.update_one({"id": rid}, {"$set": {"archived": False}})
    await audit(request, "Restoranı geri aldı", "restaurants", rid, detail=RESTAURANT_NAMES[rid])
    return {"id": rid, "archived": False}

class PinRequestIn(BaseModel):
    restaurant_id: str
    new_pin: str = Field(max_length=6)

@api.post("/restaurants/pin-request")
async def request_pin(body: PinRequestIn, request: Request, background: BackgroundTasks):
    member = request.state.member
    doc = rest.DOCS.get(body.restaurant_id)
    if member["role"] != "manager" or not doc or doc.get("archived") or body.restaurant_id != member.get("restaurant_id"):
        raise HTTPException(status_code=403, detail="Bu restorana erişiminiz yok")
    recent = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    if await db.raw.pin_requests.find_one({"restaurant_id": body.restaurant_id, "status": "pending", "created_at": {"$gte": recent}}):
        raise HTTPException(status_code=429, detail="Bekleyen bir talebiniz var. Yeni talep için 10 dakika bekleyin")
    if not re.fullmatch(PIN_RE, body.new_pin):
        raise HTTPException(status_code=422, detail="Şifre 4-6 haneli rakam olmalı")
    await db.raw.pin_requests.update_many({"restaurant_id": body.restaurant_id, "status": "pending"}, {"$set": {"status": "replaced"}})
    req = {"id": str(uuid.uuid4()), "restaurant_id": body.restaurant_id, "user_email": member.get("email", ""), "pin_hash": rest.hash_pin(body.new_pin), "status": "pending", "created_at": datetime.now(timezone.utc).isoformat()}
    await db.raw.pin_requests.insert_one({**req})
    await audit(request, "Şifre talep etti", "restaurants", body.restaurant_id, detail=doc["name"])
    background.add_task(_notify_pin_request, doc["name"], req["user_email"])
    return {"ok": True}

def _notify_pin_request(name: str, email: str) -> None:
    try:
        send_pin_request_email(name, email)
    except Exception:
        logging.exception("pin request email failed")

@api.get("/restaurants/manage/pin-requests")
async def list_pin_requests():
    rows = await db.raw.pin_requests.find({"status": "pending"}, {"_id": 0, "pin_hash": 0}).sort("created_at", -1).to_list(50)
    return [{**r, "restaurant_name": RESTAURANT_NAMES.get(r["restaurant_id"], "")} for r in rows]

@api.post("/restaurants/manage/pin-requests/{req_id}/{decision}")
async def decide_pin_request(req_id: str, decision: str, request: Request):
    if decision not in ("approve", "reject"):
        raise HTTPException(status_code=404, detail="Not found")
    req = await db.raw.pin_requests.find_one({"id": req_id, "status": "pending"}, {"_id": 0})
    if not req:
        raise HTTPException(status_code=404, detail="Talep bulunamadı")
    if decision == "approve":
        await db.raw.restaurants.update_one({"id": req["restaurant_id"]}, {"$set": {"pin_hash": req["pin_hash"]}})
    await db.raw.pin_requests.update_one({"id": req_id}, {"$set": {"status": "approved" if decision == "approve" else "rejected", "decided_at": datetime.now(timezone.utc).isoformat()}})
    await audit(request, "Şifre talebini onayladı" if decision == "approve" else "Şifre talebini reddetti", "restaurants", req["restaurant_id"], detail=f"{RESTAURANT_NAMES.get(req['restaurant_id'], '')} · {req['user_email']}")
    return {"ok": True}

@api.post("/restaurants/manage/{rid}/image/{kind}")
async def upload_restaurant_image(rid: str, kind: str, request: Request, file: UploadFile = File(...)):
    if kind not in ("logo", "cover") or rid not in rest.DOCS:
        raise HTTPException(status_code=404, detail="Restoran bulunamadı")
    ext = (file.filename or "").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else ""
    if ext not in PHOTO_TYPES:
        raise HTTPException(status_code=422, detail="Yalnızca JPG, PNG veya WEBP fotoğraf yüklenebilir")
    data = await file.read()
    if not data or len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="Fotoğraf boş veya 5 MB'den büyük")
    ext = "png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "jpg" if data[:3] == b"\xff\xd8\xff" else "webp" if data[:4] == b"RIFF" and data[8:12] == b"WEBP" else ""
    if not ext:
        raise HTTPException(status_code=422, detail="Dosya geçerli bir JPG, PNG veya WEBP değil")
    path = f"{APP_PREFIX}/restaurants/{rid}/{kind}-{uuid.uuid4()}.{ext}"
    try:
        result = await asyncio.to_thread(put_object, path, data, PHOTO_TYPES[ext])
    except Exception as exc:
        logging.exception("restaurant image upload failed")
        raise HTTPException(status_code=502, detail="Fotoğraf yüklenemedi, lütfen tekrar deneyin") from exc
    fid = str(uuid.uuid4())
    await db.files.insert_one({"id": fid, "kind": "restaurant_image", "restaurant_id": rid, "filename": file.filename, "content_type": PHOTO_TYPES[ext], "size": len(data),
                               "storage_path": result.get("path", path), "is_deleted": False, "created_at": datetime.now(timezone.utc).isoformat()})
    old = rest.DOCS[rid].get(f"{kind}_id")
    if old:
        await db.files.update_one({"id": old}, {"$set": {"is_deleted": True}})
    await db.raw.restaurants.update_one({"id": rid}, {"$set": {f"{kind}_id": fid}})
    await audit(request, "Logo yükledi" if kind == "logo" else "Kapak fotoğrafı yükledi", "restaurants", rid, detail=rest.DOCS[rid]["name"])
    return {"id": fid}

@api.delete("/restaurants/manage/{rid}/image/{kind}")
async def delete_restaurant_image(rid: str, kind: str, request: Request):
    if kind not in ("logo", "cover") or rid not in rest.DOCS:
        raise HTTPException(status_code=404, detail="Restoran bulunamadı")
    old = rest.DOCS[rid].get(f"{kind}_id")
    if old:
        await db.files.update_one({"id": old}, {"$set": {"is_deleted": True}})
    await db.raw.restaurants.update_one({"id": rid}, {"$set": {f"{kind}_id": ""}})
    await audit(request, "Logoyu kaldırdı" if kind == "logo" else "Kapak fotoğrafını kaldırdı", "restaurants", rid, detail=rest.DOCS[rid]["name"])
    return {"ok": True}

@api.post("/restaurants/unlock")
async def unlock_restaurants(body: UnlockIn, request: Request):
    member = request.state.member
    uid = member["user_id"]
    rest.throttle(uid)
    for rid, pin in body.pins.items():
        doc = rest.DOCS.get(rid)
        if not doc or doc.get("archived") or (member["role"] == "manager" and rid != member.get("restaurant_id")):
            raise HTTPException(status_code=403, detail="Bu restorana erişiminiz yok")
        if doc.get("pin_hash") and not rest.check_pin(str(pin), doc["pin_hash"]):
            rest.record_fail(uid)
            raise HTTPException(status_code=401, detail=f"{doc['name']} şifresi hatalı")
    return {"token": rest.make_token(uid, list(body.pins))}

DEFAULT_OVERHEAD = ["Kira", "Elektrik", "Su", "Doğalgaz", "İnternet / telefon", "Personel maaşları", "SGK / vergi", "Muhasebe", "Diğer"]

class OverheadItem(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    amount: float = Field(default=0, ge=0)

class OverheadIn(BaseModel):
    items: List[OverheadItem] = Field(max_length=30)
    monthly_revenue: float = Field(default=0, ge=0)

async def overhead_info() -> Dict[str, Any]:
    """Monthly fixed costs of all restaurants as a share of monthly revenue (one ratio for all)."""
    doc = await db.settings.find_one({"id": "overhead"}, {"_id": 0}) or {}
    items = doc.get("items") or [{"name": n, "amount": 0} for n in DEFAULT_OVERHEAD]
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    auto = 0.0
    for col in ("sales", "incomes"):
        auto += sum(float(r.get("amount", 0)) for r in await db.raw[col].find({"created_at": {"$gte": since}}, {"_id": 0, "amount": 1}).to_list(None))
    manual = float(doc.get("monthly_revenue") or 0)
    revenue = manual or auto
    total = round(sum(float(i["amount"]) for i in items), 2)
    ratio = round(total / revenue * 100, 2) if revenue else 0
    return {"items": items, "total": total, "revenue_auto": round(auto, 2), "revenue_manual": manual, "revenue_used": round(revenue, 2),
            "revenue_source": "manual" if manual else "auto", "ratio_pct": ratio}

@api.get("/overhead")
async def get_overhead():
    return await overhead_info()

@api.put("/overhead")
async def put_overhead(body: OverheadIn, request: Request):
    await db.settings.update_one({"id": "overhead"}, {"$set": {"items": [i.model_dump() for i in body.items if i.name.strip()], "monthly_revenue": body.monthly_revenue}}, upsert=True)
    info = await overhead_info()
    await audit(request, "Sabit gider güncelledi", "settings", "overhead", detail=f"Aylık {info['total']:g} ₺ · oran %{info['ratio_pct']:g}")
    return info

def with_overhead(row: Dict[str, Any], ratio_pct: float) -> Dict[str, Any]:
    price, cost, r = row["price"], row["cost"], ratio_pct / 100
    share = round(price * r, 2)
    full = round(cost + share, 2)
    room = 1 - row["target_margin"] / 100 - r
    return {**row, "overhead_cost": share, "full_cost": full, "net_profit": round(price - full, 2), "net_margin": _margin(price, full) if price else None,
            "suggested_with_overhead": math.ceil(round(cost / room, 6)) if cost > 0 and room > 0.01 else None}

@api.get("/product-costs")
async def product_costs():
    inventory = await db.raw.inventory.find({}, {"_id": 0}).to_list(None)
    by_id = {i["id"]: i for i in inventory}
    local = {(i.get("restaurant_id"), _tr_key(i["name"])): i for i in inventory}
    averages = await average_prices()
    rows = []
    for p in sorted(await list_items("products", limit=None), key=lambda x: (x.get("category") or "", x["name"])):
        per = {r["id"]: {"cost": 0.0, "missing": []} for r in RESTAURANTS}
        lines = []
        for item in p.get("recipe", []):
            base = by_id.get(item["inventory_id"])
            if not base:
                continue
            amount, line = float(item["amount"]), {}
            for r in RESTAURANTS:
                it = local.get((r["id"], _tr_key(base["name"])))
                price = float((it or {}).get("unit_cost", 0))
                line[r["id"]] = round(amount * price, 2) if price else None
                if price:
                    per[r["id"]]["cost"] += amount * price
                else:
                    per[r["id"]]["missing"].append(base["name"])
            lines.append({"name": base["name"], "unit": base.get("unit", ""), "amount": amount, "unit_price": round(averages.get(base["id"], 0), 2),
                          "cost": round(amount * averages.get(base["id"], 0), 2), "per_restaurant": line})
        price, cost = float(p.get("price", 0)), float(p.get("cost", 0))
        for r in RESTAURANTS:
            c = round(per[r["id"]]["cost"], 2)
            per[r["id"]].update(cost=c, margin=_margin(price, c) if p.get("recipe") and not per[r["id"]]["missing"] else None)
        rows.append({"id": p["id"], "name": p["name"], "category": p.get("category", ""), "price": price, "cost": cost, "has_recipe": bool(p.get("recipe")),
                     "profit": round(price - cost, 2), "margin": _margin(price, cost), "food_cost_pct": round(cost / price * 100, 1) if price else None,
                     "target_margin": float(p.get("target_margin") or 0) or 65, "suggested_price": suggested_price(p), "lines": lines, "per_restaurant": per})
    with_recipe = [r for r in rows if r["has_recipe"] and r["price"]]
    overhead = await overhead_info()
    rows = [with_overhead(r, overhead["ratio_pct"]) for r in rows]
    with_recipe = [r for r in rows if r["has_recipe"] and r["price"]]
    costed = [r for r in rows if r["cost"] > 0 and r["price"]]
    summary = {"products": len(rows), "with_recipe": len(with_recipe), "avg_food_cost_pct": round(sum(r["food_cost_pct"] for r in with_recipe) / len(with_recipe), 1) if with_recipe else None,
               "below_target": sum(1 for r in with_recipe if r["margin"] < r["target_margin"]), "losing": sum(1 for r in costed if r["net_profit"] < 0)}
    return {"restaurants": RESTAURANTS, "summary": summary, "overhead": overhead, "products": rows}

def created_for(day: str, fallback: str) -> str:
    """Keep entries dated on the day the user picked so reports and the cash count see them on that day."""
    if local_day(fallback) == day:
        return fallback
    return datetime.combine(date_cls.fromisoformat(day), datetime.min.time().replace(hour=12), TZ).astimezone(timezone.utc).isoformat()

def invoice_note(inv: Dict[str, Any]) -> str:
    return f"Fatura {inv.get('invoice_no') or ''} · {inv['supplier']}".replace("  ", " ")

async def app_settings() -> Dict[str, Any]:
    doc = await db.settings.find_one({"id": "app"}, {"_id": 0}) or {}
    return {"product_sales": bool(doc.get("product_sales", False))}

class SettingsIn(BaseModel):
    product_sales: bool

@api.get("/settings")
async def get_settings():
    return await app_settings()

@api.put("/settings")
async def put_settings(body: SettingsIn, request: Request):
    await db.settings.update_one({"id": "app"}, {"$set": body.model_dump()}, upsert=True)
    await audit(request, "Ayar değiştirdi", "settings", "app", detail=f"Ürün bazlı satış {'açık' if body.product_sales else 'kapalı'}")
    return body.model_dump()

class InvoicePayIn(BaseModel):
    payment: str = Field(default="Havale", pattern="^(Nakit|Kart|Havale)$")
    date: str = Field(default="", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    record_expense: bool = True

async def _invoice(invoice_id: str) -> Dict[str, Any]:
    inv = await db.invoices.find_one({"id": invoice_id}, {"_id": 0})
    if not inv:
        raise HTTPException(status_code=404, detail="Fatura bulunamadı")
    return inv

@api.post("/invoices/{invoice_id}/pay")
async def pay_invoice(invoice_id: str, body: InvoicePayIn, request: Request):
    await _invoice(invoice_id)
    inv = await db.invoices.find_one_and_update({"id": invoice_id, "status": "Ödenmedi"}, {"$set": {"status": "Ödendi"}}, projection={"_id": 0})
    if not inv:
        raise HTTPException(status_code=409, detail="Fatura zaten ödenmiş")
    day = body.date or datetime.now(TZ).date().isoformat()
    expense_id = ""
    if body.record_expense:
        exp = ExpenseEntry(category=inv.get("category") or "Fatura", amount=inv["amount"], supplier=inv["supplier"], note=invoice_note(inv), payment=body.payment, invoice_id=invoice_id).model_dump()
        exp["created_at"] = created_for(day, exp["created_at"])
        await db.expenses.insert_one({**exp, "restaurant_id": inv["restaurant_id"]})
        expense_id = exp["id"]
    await db.invoices.update_one({"id": invoice_id}, {"$set": {"status": "Ödendi", "paid_at": day, "paid_payment": body.payment, "expense_id": expense_id}})
    await audit(request, "Ödendi", "invoices", invoice_id, detail=f"{inv['supplier']} · {inv['amount']:g} ₺ · {body.payment}{' · gidere yazıldı' if expense_id else ''}")
    return {**inv, "status": "Ödendi", "paid_at": day, "paid_payment": body.payment, "expense_id": expense_id}

@api.post("/invoices/{invoice_id}/unpay")
async def unpay_invoice(invoice_id: str, request: Request):
    inv = await _invoice(invoice_id)
    if inv.get("expense_id"):
        await db.expenses.delete_many({"id": inv["expense_id"]})
    await db.invoices.update_one({"id": invoice_id}, {"$set": {"status": "Ödenmedi", "paid_at": "", "paid_payment": "", "expense_id": ""}})
    await audit(request, "Ödeme geri alındı", "invoices", invoice_id, detail=f"{inv['supplier']} · {inv['amount']:g} ₺")
    return {"ok": True}

UPLOAD_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "heic": "image/heic", "heif": "image/heif", "pdf": "application/pdf"}
MAX_UPLOAD = 10 * 1024 * 1024

@api.post("/invoices/{invoice_id}/files")
async def upload_invoice_file(invoice_id: str, request: Request, file: UploadFile = File(...)):
    inv = await _invoice(invoice_id)
    ext = (file.filename or "").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else ""
    if ext not in UPLOAD_TYPES:
        raise HTTPException(status_code=422, detail="Yalnızca fotoğraf (JPG, PNG, WEBP, HEIC) veya PDF yüklenebilir")
    data = await file.read()
    if not data or len(data) > MAX_UPLOAD:
        raise HTTPException(status_code=422, detail="Dosya boş veya 10 MB'den büyük")
    if len([f for f in inv.get("files", [])]) >= 10:
        raise HTTPException(status_code=422, detail="Bir faturaya en fazla 10 dosya eklenebilir")
    path = f"{APP_PREFIX}/invoices/{inv['restaurant_id']}/{uuid.uuid4()}.{ext}"
    try:
        result = await asyncio.to_thread(put_object, path, data, UPLOAD_TYPES[ext])
    except Exception as exc:
        logging.exception("invoice upload failed")
        raise HTTPException(status_code=502, detail="Dosya depoya yüklenemedi, lütfen tekrar deneyin") from exc
    meta = {"id": str(uuid.uuid4()), "filename": file.filename, "content_type": UPLOAD_TYPES[ext], "size": len(data), "created_at": datetime.now(timezone.utc).isoformat()}
    await db.files.insert_one({**meta, "invoice_id": invoice_id, "restaurant_id": inv["restaurant_id"], "storage_path": result.get("path", path), "is_deleted": False})
    await db.invoices.update_one({"id": invoice_id}, {"$push": {"files": meta}})
    await audit(request, "Dosya ekledi", "invoices", invoice_id, detail=f"{inv['supplier']} · {file.filename}")
    return meta

PHOTO_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}

@api.post("/products/{product_id}/photo")
async def upload_product_photo(product_id: str, request: Request, file: UploadFile = File(...)):
    product = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Ürün bulunamadı")
    ext = (file.filename or "").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else ""
    if ext not in PHOTO_TYPES:
        raise HTTPException(status_code=422, detail="Yalnızca JPG, PNG veya WEBP fotoğraf yüklenebilir")
    data = await file.read()
    if not data or len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="Fotoğraf boş veya 5 MB'den büyük")
    path = f"{APP_PREFIX}/products/{product_id}/{uuid.uuid4()}.{ext}"
    try:
        result = await asyncio.to_thread(put_object, path, data, PHOTO_TYPES[ext])
    except Exception as exc:
        logging.exception("product photo upload failed")
        raise HTTPException(status_code=502, detail="Fotoğraf yüklenemedi, lütfen tekrar deneyin") from exc
    meta = {"id": str(uuid.uuid4()), "filename": file.filename, "content_type": PHOTO_TYPES[ext], "size": len(data), "created_at": datetime.now(timezone.utc).isoformat()}
    await db.files.insert_one({**meta, "kind": "product_photo", "product_id": product_id, "storage_path": result.get("path", path), "is_deleted": False})
    if product.get("photo"):
        await db.files.update_one({"id": product["photo"]["id"]}, {"$set": {"is_deleted": True}})
    await db.products.update_one({"id": product_id}, {"$set": {"photo": meta}})
    await audit(request, "Fotoğraf ekledi", "products", product_id, detail=product["name"])
    return meta

@api.delete("/products/{product_id}/photo")
async def delete_product_photo(product_id: str, request: Request):
    product = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Ürün bulunamadı")
    if product.get("photo"):
        await db.files.update_one({"id": product["photo"]["id"]}, {"$set": {"is_deleted": True}})
    await db.products.update_one({"id": product_id}, {"$set": {"photo": {}}})
    await audit(request, "Fotoğraf sildi", "products", product_id, detail=product["name"])
    return {"ok": True}

@api.get("/public/photos/{file_id}")
async def public_photo(file_id: str):
    record = await db.files.find_one({"id": file_id, "kind": {"$in": ["product_photo", "restaurant_image"]}, "is_deleted": False}, {"_id": 0})
    if not record:
        raise HTTPException(status_code=404, detail="Fotoğraf bulunamadı")
    try:
        data, _ = await asyncio.to_thread(get_object, record["storage_path"])
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Fotoğraf bulunamadı") from exc
    return Response(content=data, media_type=record["content_type"], headers={"Cache-Control": "public, max-age=86400"})

@api.get("/files/{file_id}")
async def download_file(file_id: str):
    record = await db.files.find_one({"id": file_id, "is_deleted": False}, {"_id": 0})
    if not record or not record.get("invoice_id") or not await db.invoices.find_one({"id": record["invoice_id"]}):
        raise HTTPException(status_code=404, detail="Dosya bulunamadı")
    data, _ = await asyncio.to_thread(get_object, record["storage_path"])
    return Response(content=data, media_type=record["content_type"], headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(record['filename'])}"})

@api.delete("/invoices/{invoice_id}/files/{file_id}")
async def delete_invoice_file(invoice_id: str, file_id: str, request: Request):
    inv = await _invoice(invoice_id)
    await db.files.update_one({"id": file_id, "invoice_id": invoice_id}, {"$set": {"is_deleted": True}})
    await db.invoices.update_one({"id": invoice_id}, {"$pull": {"files": {"id": file_id}}})
    await audit(request, "Dosya sildi", "invoices", invoice_id, detail=inv["supplier"])
    return {"ok": True}

def make_crud(name: str, model: type[BaseModel]):
    @api.get(f"/{name}")
    async def get_items():
        return await list_items(name)
    @api.post(f"/{name}", response_model=model)
    async def create_item(item: model, request: Request):
        doc = item.model_dump()
        if name in SCOPED:
            specific_rid()
        if name == "attendance":
            await validate_attendance(doc)
        if name == "incomes":
            doc["created_at"] = created_for(doc["date"], doc["created_at"])
        if name == "invoices":
            doc.update(status="Ödenmedi", paid_at="", paid_payment="", expense_id="", files=[])
        if name == "products":
            doc = await with_recipe_cost(doc)
        if name == "sales" and getattr(request.state, "member", {}).get("role") == "staff":
            product = await db.products.find_one({"id": doc.get("product_id")}, {"_id": 0})
            if not product:
                raise HTTPException(status_code=422, detail="Menü ürünü seçin")
            doc.update(product_name=product["name"], unit_price=float(product["price"]), unit_cost=float(product.get("cost", 0)), amount=round(float(doc["quantity"]) * float(product["price"]), 2))
        if name == "waste":
            await apply_waste(doc, 1, f"Fire · {doc['reason']}")
        if name == "sales":
            await insert_sale(doc, request)
            return model(**doc)
        if name == "expenses" and doc.get("purchases"):
            _purchase_total(doc)
            await apply_purchases(doc, 1, f"Alış · {doc['category']}")
        await db[name].insert_one({**doc})
        if name == "inventory" and doc["quantity"]:
            await log_movement(doc, doc["quantity"], "İlk kayıt")
        if name == "inventory":
            await recompute_product_costs()
        await audit(request, "Ekledi", name, doc["id"], doc)
        return model(**doc)
    @api.put(f"/{name}/{{item_id}}", response_model=model)
    async def update_item(item_id: str, item: model, request: Request):
        old = await db[name].find_one({"id": item_id}, {"_id": 0})
        if not old:
            raise HTTPException(status_code=404, detail="Kayıt bulunamadı")
        doc = {**item.model_dump(), "id": item_id, "created_at": old["created_at"]}
        if name == "attendance":
            await validate_attendance(doc)
        if name == "incomes":
            doc["created_at"] = created_for(doc["date"], old["created_at"])
        if name == "invoices":
            doc.update({k: old.get(k, doc[k]) for k in ("status", "paid_at", "paid_payment", "expense_id", "files")})
            if old.get("expense_id"):
                await db.expenses.update_one({"id": old["expense_id"]}, {"$set": {"amount": doc["amount"], "supplier": doc["supplier"], "note": invoice_note(doc)}})
        if name == "expenses":
            doc["invoice_id"] = old.get("invoice_id", "")
        if name == "products":
            doc["photo"] = old.get("photo", {})
        if name == "products":
            doc = await with_recipe_cost(doc)
        if name == "expenses" and (old.get("purchases") or doc.get("purchases")):
            await apply_purchases(old, -1, "Alış düzeltildi (eski kayıt geri alındı)")
            old_total = sum(float(p["quantity"]) * float(p.get("unit_price", 0)) for p in old.get("purchases", []))
            if old.get("purchases") and abs(float(old.get("amount", 0)) - old_total) < 0.01 and abs(float(doc.get("amount", 0)) - old_total) < 0.01:
                doc["amount"] = 0
            _purchase_total(doc)
            await apply_purchases(doc, 1, f"Alış düzeltildi · {doc['category']}")
        if name == "staff":
            doc["request_token"] = old.get("request_token") or doc["request_token"]
        if name == "sales":
            doc["created_by"] = old.get("created_by", "")
        if name == "waste":
            key = _tr_key(doc["inventory_name"])
            if not any(_tr_key(i["name"]) == key for i in await list_items("inventory", limit=None)):
                raise HTTPException(status_code=422, detail="Stokta bu isimde malzeme yok")
            await apply_waste(old, -1, "Fire düzeltildi (eski kayıt geri alındı)")
            doc["inventory_id"] = ""
            await apply_waste(doc, 1, f"Fire düzeltildi · {doc['reason']}")
        if name == "orders":
            await sync_order_delivery(old, doc)
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
        await audit(request, "Düzenledi", name, item_id, doc)
        return model(**doc)
    @api.delete(f"/{name}/{{item_id}}")
    async def delete_item(item_id: str, request: Request):
        if name == "tables":
            await db.kitchen_tickets.delete_many({"table_id": item_id, "status": {"$in": ["Yeni", "Hazırlanıyor"]}})
        if name == "tables" and await db.table_orders.find_one({"table_id": item_id, "status": {"$in": ["Açık", "Kapanıyor"]}}):
            raise HTTPException(status_code=409, detail="Masada açık hesap var; önce hesabı kapatın veya iptal edin")
        old = await db[name].find_one_and_delete({"id": item_id}, {"_id": 0})
        if not old:
            raise HTTPException(status_code=404, detail="Kayıt bulunamadı")
        if name == "sales":
            await apply_moves(old.get("stock_moves", []), -1, old, "Satış silindi (stok iade)")
        if name == "expenses" and old.get("purchases"):
            await apply_purchases(old, -1, "Alış silindi (stoktan çıkarıldı)")
        if name == "expenses" and old.get("invoice_id"):
            await db.invoices.update_one({"id": old["invoice_id"]}, {"$set": {"status": "Ödenmedi", "paid_at": "", "paid_payment": "", "expense_id": ""}})
        if name == "invoices" and old.get("expense_id"):
            await db.expenses.delete_many({"id": old["expense_id"]})
        if name == "invoices":
            await db.files.update_many({"invoice_id": item_id}, {"$set": {"is_deleted": True}})
        if name == "products":
            await db.files.update_many({"product_id": item_id}, {"$set": {"is_deleted": True}})
        if name == "waste":
            await apply_waste(old, -1, "Fire silindi (stok iade)")
        if name == "orders" and old.get("expense_id"):
            await remove_expense(old["expense_id"])
        if name == "staff":
            for related in ("shifts", "leaves", "advances", "leave_requests", "attendance"):
                await db[related].delete_many({"staff_id": item_id})
        if name == "inventory":
            await log_movement({**old, "quantity": 0}, -float(old.get("quantity", 0)), "Malzeme silindi")
            await recompute_product_costs()
        await audit(request, "Sildi", name, item_id, old)
        return {"ok": True}
    return get_items, create_item, update_item, delete_item

for collection_name, collection_model in COLLECTIONS.items():
    make_crud(collection_name, collection_model)

app = FastAPI(title="GÖKBOSS POS API")
app.include_router(api)
app.include_router(clerk_router)  # /api/clerk/config and /api/__clerk/*
app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","), allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
async def startup():
    await db.cron_runs.create_index("run_id", unique=True)
    with suppress(Exception):
        await asyncio.to_thread(init_storage)
    if not await db.raw.restaurants.count_documents({}):
        now = datetime.now(timezone.utc).isoformat()
        await db.raw.restaurants.insert_many([{**r, "email": "", "pin_hash": "", "archived": False, "created_at": f"{now}-{i}"} for i, r in enumerate(rest.SEED)])
    rest.refresh(await db.raw.restaurants.find({}, {"_id": 0}).sort("created_at", 1).to_list(200))
    for name in SCOPED:
        await db.raw[name].update_many({"restaurant_id": {"$exists": False}}, {"$set": {"restaurant_id": DEFAULT_RESTAURANT}})

@app.on_event("shutdown")
async def shutdown():
    client.close()