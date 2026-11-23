import asyncio
import hmac
import secrets
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
from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from fastapi.responses import Response

from exports import build_excel, build_pdf, build_payroll_excel, build_payslip_pdf
from mailer import send_cash_reminder_email, send_leave_request_email, send_monthly_email, send_report_email, send_weekly_email
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")
client = AsyncIOMotorClient(os.environ["MONGO_URL"])
from scope import DEFAULT_RESTAURANT, RESTAURANT_IDS, RESTAURANT_NAMES, RESTAURANTS, SCOPED, ScopedDB, current_rid, specific_rid
db = ScopedDB(client[os.environ["DB_NAME"]])
try:  # launched as `backend.server` (the default)
    from backend.clerk_auth import clerk_router, require_user
except ModuleNotFoundError:  # launched from inside backend/ as `server`
    from clerk_auth import clerk_router, require_user
import requests as http_requests
from pymongo import ReturnDocument as _RD

# The role list is code, so every publish ships it to Live. Highest first; keep `admin`.
ROLES = ["admin", "staff", "member"]
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

async def current_member(request: Request) -> Dict[str, Any]:
    user = require_user(request)
    uid = user["user_id"]
    member = await db.users.find_one({"user_id": uid}, {"_id": 0})
    if member is None or not member.get("role"):
        info = await asyncio.to_thread(_clerk_user, uid)
        role = "admin" if _is_admin_email(info) else DEFAULT_ROLE
        email = next((e["email_address"] for e in info["email_addresses"] if e["id"] == info.get("primary_email_address_id")), "")
        await db.users.update_one({"user_id": uid, "role": {"$in": [None, ""]}}, {"$set": {"role": role}})
        member = await db.users.find_one_and_update({"user_id": uid}, {"$setOnInsert": {"user_id": uid, "role": role, "email": email, "created_at": datetime.now(timezone.utc).isoformat()}},
                                                    upsert=True, projection={"_id": 0}, return_document=_RD.AFTER)
    if member.get("env") != ENV:
        await db.users.update_one({"user_id": uid}, {"$set": {"env": ENV}})
    return {**member, "env": ENV, "role": effective_role(member["role"])}

STAFF_ROUTES = [("GET", r"/api/staff-view"), ("POST", r"/api/sales"), ("POST", r"/api/inventory/[\w-]+/count"), ("GET", r"/api/tables-view"),
                ("POST", r"/api/tables/[\w-]+/(items|close|cancel|pay)"), ("POST", r"/api/tables/[\w-]+/pending/[\w-]+/remove"),
                ("GET", r"/api/kitchen"), ("POST", r"/api/kitchen/[\w-]+/status"), ("GET", r"/api/attendance/me"), ("POST", r"/api/attendance/clock")]
ALL_MODE_WRITES = r"/api/(products|suppliers|users|email|price-alerts|leave-requests)(/.*)?|/api/staff/[\w-]+/request-link"

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
    return str(doc.get("name") or doc.get("supplier") or doc.get("id", ""))

async def audit(request: Request, action: str, collection: str, item_id: str, doc: Dict[str, Any] | None = None, detail: str = "") -> None:
    member = getattr(request.state, "member", None) or {}
    await db.audit_logs.insert_one({"id": str(uuid.uuid4()), "user_id": member.get("user_id", ""), "user_email": member.get("email", ""), "role": member.get("role", ""),
                                    "restaurant_id": current_rid.get() or "", "action": action, "collection": collection, "item_id": item_id, "summary": detail or _label(collection, doc),
                                    "created_at": datetime.now(timezone.utc).isoformat()})

async def dashboard_guard(request: Request) -> None:
    """Every /api route except the staff leave link and cron webhooks is admin-only."""
    if request.url.path.startswith(PUBLIC_PREFIXES):
        return
    if request.url.path in ("/api/me",):
        return
    member = await current_member(request)
    request.state.member = member
    if member["role"] == "staff" and staff_allowed(request.method, request.url.path):
        current_rid.set(member.get("restaurant_id") or DEFAULT_RESTAURANT)
        return
    if member["role"] != "admin":
        raise HTTPException(status_code=403, detail="Bu panele erişim yetkiniz yok")
    rid = request.headers.get("x-restaurant") or DEFAULT_RESTAURANT
    if rid not in RESTAURANT_IDS and rid != "all":
        raise HTTPException(status_code=400, detail="Geçersiz restoran")
    if rid == "all" and request.method != "GET" and not re.fullmatch(ALL_MODE_WRITES, request.url.path):
        raise HTTPException(status_code=400, detail="Bu işlem için üstten bir restoran seçin")
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

COLLECTIONS = {"sales": SalesEntry, "expenses": ExpenseEntry, "inventory": InventoryEntry, "staff": StaffEntry, "cash": CashEntry, "products": ProductEntry, "suppliers": SupplierEntry, "shifts": ShiftEntry, "leaves": LeaveEntry, "advances": AdvanceEntry, "orders": OrderEntry, "waste": WasteEntry, "tables": TableEntry, "tips": TipEntry, "attendance": AttendanceEntry}

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
    week_sales = await list_items("sales", week_start, None)
    week_expenses = await list_items("expenses", week_start, None)
    weekly = []
    for offset in range(6, -1, -1):
        day = (today - timedelta(days=offset)).isoformat()
        weekly.append({"date": day, "revenue": _total(i for i in week_sales if local_day(i["created_at"]) == day), "expenses": _total(i for i in week_expenses if local_day(i["created_at"]) == day)})
    revenue, spent = weekly[-1]["revenue"], weekly[-1]["expenses"]
    low_stock = sum(1 for item in inventory if float(item.get("quantity", 0)) <= float(item.get("minimum", 0)))
    all_inventory = await db.raw.inventory.find({}, {"_id": 0, "id": 1, "name": 1, "unit": 1, "unit_cost": 1, "restaurant_id": 1, "created_at": 1}).sort("created_at", 1).to_list(None)
    extra = {"all_inventory": all_inventory, "tables": await db.tables.find({}, {"_id": 0}).sort("name", 1).to_list(None), "tips": await list_items("tips"),
             "attendance": await list_items("attendance", limit=300), "restaurant_id": current_rid.get()}
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
    waste = await db.waste.find({"created_at": {"$gte": since, "$lt": until}}, {"_id": 0}).to_list(None)
    return {"payments": payment_breakdown(sales), "waste_cost": round(sum(float(w.get("cost", 0)) for w in waste), 2), "waste_count": len(waste), "period": period, "start": begin.isoformat(), "end": (finish - timedelta(seconds=1)).isoformat(), "revenue": revenue, "expenses": spent, "profit": revenue - spent, "sales_count": len(sales),
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
    rid = member.get("restaurant_id") or DEFAULT_RESTAURANT
    return {"user_id": member["user_id"], "email": member.get("email", ""), "role": member["role"], "restaurants": RESTAURANTS,
            "restaurant_id": rid, "restaurant_name": RESTAURANT_NAMES[rid], "staff_id": member.get("staff_id", "")}

@api.get("/users")
async def list_users():
    people = await db.users.find(IN_ENV, {"_id": 0}).to_list(1000)
    return {"roles": ROLES, "users": [{**p, "role": effective_role(p.get("role"))} for p in people]}

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
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for p in sorted(await list_items("products", limit=None), key=lambda x: x["name"]):
        if p.get("active", True):
            groups.setdefault(p.get("category") or "Menü", []).append({"name": p["name"], "price": p.get("price", 0)})
    return {"name": "GÖKBOSS", "categories": [{"category": k, "items": v} for k, v in sorted(groups.items())]}

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
    sales = [item for item in await list_items("sales", since, None) if same_day(item)]
    expenses = [item for item in await list_items("expenses", since, None) if same_day(item)]
    cash_logs = [item for item in await list_items("cash", since, None) if same_day(item)]
    opening = float(cash_logs[-1].get("opening", 0)) if cash_logs else 0
    actual = float(cash_logs[0].get("closing", 0)) if cash_logs else 0
    sales_total, expenses_total = _total(sales), _total(expenses)
    payments = payment_breakdown(sales)
    expected = opening + payments["Nakit"] - expenses_total
    return {"date": target, "opening": opening, "sales": sales_total, "cash_sales": payments["Nakit"], "payments": payments, "expenses": expenses_total, "expected_closing": expected, "actual_closing": actual, "difference": actual - expected, "has_closing": bool(cash_logs)}

PAYMENTS = ("Nakit", "Kart", "Yemek kartı")

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

def suggested_price(product: Dict[str, Any]) -> float | None:
    margin = float(product.get("target_margin") or 0) or 65
    cost = float(product.get("cost", 0))
    return math.ceil(cost / (1 - margin / 100)) if cost > 0 and margin < 100 else None

@api.post("/products/apply-suggested")
async def apply_suggested_prices(payload: Dict[str, List[str]], request: Request):
    ids = set(payload.get("product_ids", []))
    changed = []
    for product in await list_items("products", limit=None):
        price = suggested_price(product)
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
    return [{**t, "order": orders.get(t["id"]), "ready_count": ready.get(t["id"], 0)} for t in tables]

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

def _sale_doc(item: Dict[str, Any], quantity: float, amount: float, payment: str, table: Dict[str, Any]) -> Dict[str, Any]:
    return SalesEntry(product_id=item["product_id"], product_name=item["product_name"], quantity=round(quantity, 4), unit_price=item["unit_price"], channel="Salon",
                      payment=payment, amount=round(amount, 2), note=f"Masa {table['name']}").model_dump()

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
                await insert_sale(_sale_doc(row, row["quantity"] * share, row["quantity"] * row["unit_price"] * share, p["payment"], table), request)
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
            target = InventoryEntry(name=source["name"], unit=source.get("unit", "adet"), minimum=source.get("minimum", 0), unit_cost=source.get("unit_cost", 0),
                                    target=source.get("target", 0), supplier=source.get("supplier", "")).model_dump()
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
    for inv_id, q in wanted.items():
        item = sources[inv_id]
        await apply_moves([{"inventory_id": inv_id, "delta": -q}], 1, ref, f"Transfer → {doc['to_name']}")
        target = await _move_in(body.to_restaurant, item, q, ref, f"Transfer ← {doc['from_name']}")
        doc["items"].append({"name": item["name"], "unit": item.get("unit", ""), "quantity": q, "unit_cost": float(item.get("unit_cost", 0)), "from_id": inv_id, "to_id": target["id"]})
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
async def restaurants_summary():
    rows = []
    for r in RESTAURANTS:
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
    summary = {"products": len(rows), "with_recipe": len(with_recipe), "avg_food_cost_pct": round(sum(r["food_cost_pct"] for r in with_recipe) / len(with_recipe), 1) if with_recipe else None,
               "below_target": sum(1 for r in with_recipe if r["margin"] < r["target_margin"])}
    return {"restaurants": RESTAURANTS, "summary": summary, "products": rows}

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
        if name == "tables" and await db.table_orders.find_one({"table_id": item_id, "status": {"$in": ["Açık", "Kapanıyor"]}}):
            raise HTTPException(status_code=409, detail="Masada açık hesap var; önce hesabı kapatın veya iptal edin")
        old = await db[name].find_one_and_delete({"id": item_id}, {"_id": 0})
        if not old:
            raise HTTPException(status_code=404, detail="Kayıt bulunamadı")
        if name == "sales":
            await apply_moves(old.get("stock_moves", []), -1, old, "Satış silindi (stok iade)")
        if name == "expenses" and old.get("purchases"):
            await apply_purchases(old, -1, "Alış silindi (stoktan çıkarıldı)")
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
    for name in SCOPED:
        await db.raw[name].update_many({"restaurant_id": {"$exists": False}}, {"$set": {"restaurant_id": DEFAULT_RESTAURANT}})

@app.on_event("shutdown")
async def shutdown():
    client.close()