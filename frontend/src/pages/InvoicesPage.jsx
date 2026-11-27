import { useEffect, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { ChevronDown, ChevronLeft, ChevronRight, Search } from "lucide-react";
import { InvoiceList } from "@/components/CashBook";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const money = (n) => new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY", maximumFractionDigits: 2 }).format(n || 0);
const thisMonth = () => new Date().toLocaleDateString("sv-SE").slice(0, 7);
const shiftMonth = (m, d) => { const [y, mo] = m.split("-").map(Number); const t = new Date(y, mo - 1 + d, 1); return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}`; };
const monthLabel = (m) => new Date(`${m}-01T12:00:00`).toLocaleDateString("tr-TR", { month: "long", year: "numeric" });
const trDate = (d) => (d ? new Date(`${d}T12:00:00`).toLocaleDateString("tr-TR", { day: "2-digit", month: "short", year: "numeric" }) : "");

function PeriodBar({ month, setMonth }) {
  const all = month === "all";
  return (
    <div className="inv-period" data-testid="invoice-period">
      <button className="icon-button" disabled={all} onClick={() => setMonth(shiftMonth(month, -1))} aria-label="Önceki ay" data-testid="invoice-month-prev"><ChevronLeft size={16} /></button>
      <b data-testid="invoice-month-label">{all ? "Tüm zamanlar" : monthLabel(month)}</b>
      <button className="icon-button" disabled={all || month >= thisMonth()} onClick={() => setMonth(shiftMonth(month, 1))} aria-label="Sonraki ay" data-testid="invoice-month-next"><ChevronRight size={16} /></button>
      <button className={`report-tab ${all ? "active" : ""}`} onClick={() => setMonth(all ? thisMonth() : "all")} data-testid="invoice-month-all">Tüm zamanlar</button>
    </div>
  );
}

function GroupRow({ g, idx, open, onToggle, by }) {
  return (
    <div className={`inv-group ${open ? "open" : ""}`} data-testid={`invoice-group-${idx}`}>
      <button className="inv-group-line" onClick={onToggle} data-testid={`invoice-group-toggle-${idx}`}>
        <span className="inv-group-name"><b data-testid={`invoice-group-name-${idx}`}>{g.name}</b><small>{g.count} fatura · son {trDate(g.last_date)}</small></span>
        <span className="inv-num"><small>Toplam</small><strong data-testid={`invoice-group-total-${idx}`}>{money(g.total)}</strong></span>
        <span className="inv-num green-text"><small>Ödenen</small>{money(g.paid)}</span>
        <span className={`inv-num ${g.unpaid ? "amber-text" : ""}`}><small>Kalan</small><span data-testid={`invoice-group-unpaid-${idx}`}>{money(g.unpaid)}</span></span>
        <ChevronDown size={16} className="inv-chev" />
      </button>
      {open && <div className="inv-group-items">{g.invoices.map((i) => (
        <div key={i.id} className="inv-sub"><span>{trDate(i.date)}</span><span>{i.invoice_no ? `No ${i.invoice_no}` : "—"}</span><span className="muted">{by === "supplier" ? i.category : i.supplier}</span><b>{money(i.amount)}</b><em className={i.status === "Ödendi" ? "green-text" : "amber-text"}>{i.status}</em></div>
      ))}<small className="muted">KDV toplamı: {money(g.vat)}</small></div>}
    </div>
  );
}

function InvoiceGroups({ refreshKey }) {
  const [by, setBy] = useState("supplier");
  const [month, setMonth] = useState(thisMonth);
  const [q, setQ] = useState("");
  const [data, setData] = useState(null);
  const [open, setOpen] = useState(null);
  useEffect(() => {
    const t = setTimeout(() => axios.get(`${API}/invoices/groups`, { params: { by, month, q } }).then(({ data: d }) => setData(d)).catch(() => setData({ groups: [], total: 0, unpaid: 0, count: 0 })), 250);
    return () => clearTimeout(t);
  }, [by, month, q, refreshKey]);
  useEffect(() => setOpen(null), [by, month, q]);
  return (
    <section className="panel inv-groups" data-testid="invoice-groups">
      <div className="panel-head"><div><h3>Aynı isimdeki faturaların toplamı</h3><span className="muted">İsmi yazın; büyük/küçük harf ve boşluk farkı olsa da aynı isimdekiler tek satırda toplanır</span></div></div>
      <div className="inv-controls">
        <div className="staff-channels">{[["supplier", "Firmaya göre"], ["category", "Konuya göre"]].map(([k, l]) => <button key={k} className={`report-tab ${by === k ? "active" : ""}`} onClick={() => setBy(k)} data-testid={`invoice-group-by-${k}`}>{l}</button>)}</div>
        <label className="inv-search"><Search size={15} /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder={by === "supplier" ? "Firma adı yazın, örn. Metro" : "Fatura konusu yazın, örn. Elektrik"} data-testid="invoice-group-search" /></label>
        <PeriodBar month={month} setMonth={setMonth} />
      </div>
      {data && <div className="inv-totals" data-testid="invoice-group-summary"><span>{data.count} fatura</span><span>Toplam <b data-testid="invoice-groups-total">{money(data.total)}</b></span><span>Ödenmemiş <b className="amber-text">{money(data.unpaid)}</b></span></div>}
      {data && !data.groups.length && <div className="empty-state" data-testid="invoice-groups-empty">{q ? `"${q}" adında fatura bulunamadı.` : "Bu dönemde fatura yok."}</div>}
      {data?.groups.map((g, i) => <GroupRow key={g.key} g={g} idx={i} open={open === g.key} onToggle={() => setOpen(open === g.key ? null : g.key)} by={data.by} />)}
    </section>
  );
}

export default function InvoicesPage({ data, onAdd: add, onEdit, onDelete, onReload }) {
  const onAdd = (...args) => (data.restaurant_id === "all" ? toast.error("Fatura eklemek için üstten bir restoran seçin") : add(...args));
  return <>
    <div className="welcome-row"><div><p className="eyebrow">ALIŞ FATURALARI</p><h2>Faturalar</h2><p className="muted">Faturalarınızı girin, ödemelerini takip edin ve aynı firmadan ya da aynı konudaki faturaların toplamını görün.</p></div></div>
    <InvoiceGroups refreshKey={data.invoices} />
    <section className="panel table-panel cash-book" data-testid="invoice-list-panel"><InvoiceList items={data.invoices} onAdd={onAdd} onEdit={onEdit} onDelete={onDelete} onReload={onReload} /></section>
  </>;
}
