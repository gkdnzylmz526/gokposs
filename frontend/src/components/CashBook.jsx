import { useMemo, useRef, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { CheckCircle2, FileText, Paperclip, Plus, RotateCcw, Trash2, X } from "lucide-react";
import { errorText } from "@/lib/restaurant";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const money = (n) => new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY", maximumFractionDigits: 2 }).format(n || 0);
const today = () => new Date().toLocaleDateString("sv-SE");
const trDate = (d) => (d ? new Date(`${d}T12:00:00`).toLocaleDateString("tr-TR") : "—");
const dayOf = (iso) => new Date(iso).toLocaleDateString("sv-SE");
const daysTo = (d) => Math.round((new Date(`${d}T12:00:00`) - new Date(`${today()}T12:00:00`)) / 86400000);

function IncomeList({ items, onAdd, onEdit, onDelete }) {
  const total = items.filter((i) => i.date === today()).reduce((s, i) => s + i.amount, 0);
  const grid = { gridTemplateColumns: ".9fr 1.1fr .9fr 1.6fr .9fr 90px" };
  return (
    <>
      <div className="book-head"><span className="muted">Bugün girilen gelir: <b data-testid="income-today-total">{money(total)}</b></span><button className="primary-button" data-testid="add-income-button" onClick={() => onAdd("incomes", { date: today(), payment: "Nakit", category: "POS satış" })}><Plus size={15} /> Gelir ekle</button></div>
      <div className="table-head" style={grid}><span>Tarih</span><span>Kategori</span><span>Ödeme</span><span>Açıklama</span><span>Tutar</span><span /></div>
      {!items.length && <div className="empty-state">Henüz gelir kaydı yok. POS'unuzdaki tutarları buraya girin.</div>}
      {items.slice(0, 60).map((i, idx) => <div className="table-row" style={grid} key={i.id} data-testid={`income-row-${idx}`}><span>{trDate(i.date)}</span><span>{i.category}</span><span><em className={`pay-tag pay-${i.payment.replace(" ", "-")}`}>{i.payment}</em></span><span className="muted">{i.note || "—"}</span><span className="table-amount green-text">{money(i.amount)}</span><span className="row-mini-actions"><button className="text-button tiny" data-testid={`income-edit-${idx}`} onClick={() => onEdit("incomes", i)}>Düzenle</button><button className="text-button tiny danger-inline" data-testid={`income-delete-${idx}`} onClick={() => window.confirm("Gelir kaydı silinsin mi?") && onDelete("incomes", i.id)}>Sil</button></span></div>)}
    </>
  );
}

function ExpenseList({ items, onAdd, onEdit, onDelete }) {
  const total = items.filter((i) => dayOf(i.created_at) === today()).reduce((s, i) => s + i.amount, 0);
  const grid = { gridTemplateColumns: ".9fr 1.1fr .9fr 1.6fr .9fr 90px" };
  return (
    <>
      <div className="book-head"><span className="muted">Bugünkü gider: <b data-testid="expense-today-total">{money(total)}</b></span><button className="primary-button" data-testid="add-book-expense-button" onClick={() => onAdd("expenses", { payment: "Nakit" })}><Plus size={15} /> Gider ekle</button></div>
      <div className="table-head" style={grid}><span>Tarih</span><span>Kategori</span><span>Ödeme</span><span>Açıklama</span><span>Tutar</span><span /></div>
      {!items.length && <div className="empty-state">Henüz gider kaydı yok.</div>}
      {items.slice(0, 60).map((e, idx) => <div className="table-row" style={grid} key={e.id} data-testid={`book-expense-row-${idx}`}><span>{new Date(e.created_at).toLocaleDateString("tr-TR")}</span><span>{e.category}</span><span><em className={`pay-tag pay-${(e.payment || "Nakit").replace(" ", "-")}`}>{e.payment || "Nakit"}</em></span><span className="muted">{e.note || e.supplier || "—"}{e.invoice_id && <em className="recipe-badge">fatura</em>}</span><span className="table-amount danger-inline">{money(e.amount)}</span><span className="row-mini-actions"><button className="text-button tiny" data-testid={`book-expense-edit-${idx}`} onClick={() => onEdit("expenses", e)}>Düzenle</button><button className="text-button tiny danger-inline" data-testid={`book-expense-delete-${idx}`} onClick={() => window.confirm(e.invoice_id ? "Bu gider bir fatura ödemesi. Silerseniz fatura tekrar 'Ödenmedi' olur. Devam?" : "Gider silinsin mi?") && onDelete("expenses", e.id)}>Sil</button></span></div>)}
    </>
  );
}

function PayDialog({ invoice, onClose, onDone }) {
  const [payment, setPayment] = useState("Havale");
  const [date, setDate] = useState(today());
  const [record, setRecord] = useState(true);
  const [busy, setBusy] = useState(false);
  const save = async () => { setBusy(true); try { await axios.post(`${API}/invoices/${invoice.id}/pay`, { payment, date, record_expense: record }); toast.success("Fatura ödendi olarak işaretlendi"); onDone(); onClose(); } catch (e) { toast.error(errorText(e, "İşaretlenemedi")); } finally { setBusy(false); } };
  return (
    <div className="modal-backdrop"><div className="modal" data-testid="invoice-pay-dialog">
      <button className="icon-button close" data-testid="invoice-pay-close" onClick={onClose}><X size={18} /></button>
      <span className="eyebrow">FATURA ÖDEMESİ</span><h2>{invoice.supplier} · {money(invoice.amount)}</h2>
      <div className="form-grid">
        <div className="staff-channels">{["Nakit", "Kart", "Havale"].map((p) => <button key={p} className={`report-tab ${payment === p ? "active" : ""}`} data-testid={`invoice-pay-${p}`} onClick={() => setPayment(p)}>{p}</button>)}</div>
        <label>Ödeme tarihi<input type="date" value={date} max={today()} data-testid="invoice-pay-date" onChange={(e) => setDate(e.target.value)} /></label>
        <label className="check-line"><input type="checkbox" checked={record} data-testid="invoice-pay-record" onChange={(e) => setRecord(e.target.checked)} /> Giderlere de yaz {payment === "Nakit" ? "(kasadan düşer)" : "(kasayı etkilemez)"}</label>
      </div>
      <button className="primary-button full" disabled={busy} data-testid="invoice-pay-save" onClick={save}><CheckCircle2 size={16} /> Ödendi olarak işaretle</button>
    </div></div>
  );
}

function InvoiceFiles({ invoice, onChange }) {
  const input = useRef(null);
  const [busy, setBusy] = useState(false);
  const upload = async (file) => {
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) return toast.error("Dosya 10 MB'den büyük olamaz");
    setBusy(true);
    try { const form = new FormData(); form.append("file", file); await axios.post(`${API}/invoices/${invoice.id}/files`, form); toast.success("Dosya eklendi"); onChange(); }
    catch (e) { toast.error(errorText(e, "Dosya yüklenemedi")); } finally { setBusy(false); if (input.current) input.current.value = ""; }
  };
  const open = async (f) => { const tab = window.open("", "_blank"); try { const { data } = await axios.get(`${API}/files/${f.id}`, { responseType: "blob" }); const url = URL.createObjectURL(data); if (tab) tab.location.href = url; else window.location.href = url; setTimeout(() => URL.revokeObjectURL(url), 60000); } catch { tab?.close(); toast.error("Dosya açılamadı"); } };
  const remove = async (f) => { if (!window.confirm(`${f.filename} silinsin mi?`)) return; try { await axios.delete(`${API}/invoices/${invoice.id}/files/${f.id}`); onChange(); } catch (e) { toast.error(errorText(e, "Silinemedi")); } };
  return (
    <div className="invoice-files">
      {invoice.files?.map((f, i) => <span key={f.id} className="file-chip" data-testid={`invoice-file-${invoice.id}-${i}`}><button className="file-open" data-testid={`invoice-file-open-${invoice.id}-${i}`} onClick={() => open(f)}><FileText size={12} /> {f.filename}</button><button title="Sil" data-testid={`invoice-file-delete-${invoice.id}-${i}`} onClick={() => remove(f)}><X size={11} /></button></span>)}
      <input ref={input} type="file" hidden accept="image/*,.heic,.heif,application/pdf" data-testid={`invoice-file-input-${invoice.id}`} onChange={(e) => upload(e.target.files?.[0])} />
      <button className="text-button tiny attach" disabled={busy} data-testid={`invoice-attach-${invoice.id}`} onClick={() => input.current?.click()}><Paperclip size={12} /> {busy ? "Yükleniyor…" : "Foto/PDF ekle"}</button>
    </div>
  );
}

function InvoiceList({ items, onAdd, onEdit, onDelete, onReload }) {
  const [filter, setFilter] = useState("Ödenmedi");
  const [paying, setPaying] = useState(null);
  const unpaid = items.filter((i) => i.status === "Ödenmedi");
  const overdue = unpaid.filter((i) => i.due_date && daysTo(i.due_date) < 0);
  const soon = unpaid.filter((i) => i.due_date && daysTo(i.due_date) >= 0 && daysTo(i.due_date) <= 7);
  const shown = useMemo(() => items.filter((i) => filter === "Tümü" || i.status === filter).sort((a, b) => (a.status === b.status ? (a.due_date || a.date).localeCompare(b.due_date || b.date) : a.status === "Ödenmedi" ? -1 : 1)), [items, filter]);
  const unpay = async (inv) => { if (!window.confirm("Ödeme geri alınsın mı? Bağlı gider kaydı da silinir.")) return; try { await axios.post(`${API}/invoices/${inv.id}/unpay`); toast.success("Ödeme geri alındı"); onReload(); } catch (e) { toast.error(errorText(e, "Geri alınamadı")); } };
  const sum = (list) => list.reduce((s, i) => s + i.amount, 0);
  return (
    <>
      <div className="invoice-summary">
        <div className="cost-tile amber" data-testid="invoice-unpaid-total"><span>Ödenmemiş toplam</span><strong>{money(sum(unpaid))}</strong><small>{unpaid.length} fatura</small></div>
        <div className={`cost-tile ${overdue.length ? "red" : "green"}`} data-testid="invoice-overdue"><span>Vadesi geçmiş</span><strong>{money(sum(overdue))}</strong><small>{overdue.length} fatura</small></div>
        <div className="cost-tile" data-testid="invoice-due-soon"><span>7 gün içinde ödenecek</span><strong>{money(sum(soon))}</strong><small>{soon.length} fatura</small></div>
      </div>
      <div className="book-head"><div className="staff-channels">{["Ödenmedi", "Ödendi", "Tümü"].map((f) => <button key={f} className={`report-tab ${filter === f ? "active" : ""}`} data-testid={`invoice-filter-${f}`} onClick={() => setFilter(f)}>{f}</button>)}</div><button className="primary-button" data-testid="add-invoice-button" onClick={() => onAdd("invoices", { date: today(), vat_rate: 20, category: "Malzeme alımı" })}><Plus size={15} /> Fatura ekle</button></div>
      {!shown.length && <div className="empty-state">{filter === "Ödenmedi" ? "Ödenmemiş fatura yok." : "Fatura yok."}</div>}
      {shown.map((inv, idx) => {
        const d = inv.due_date ? daysTo(inv.due_date) : null;
        const due = inv.status === "Ödendi" ? <span className="status status-green">Ödendi · {trDate(inv.paid_at)} · {inv.paid_payment}</span> : d == null ? <span className="muted">Vade yok</span> : d < 0 ? <span className="status status-red">{-d} gün gecikti</span> : d === 0 ? <span className="status status-yellow">Bugün son gün</span> : <span className={d <= 7 ? "status status-yellow" : "muted"}>{d} gün kaldı</span>;
        return (
          <div className={`invoice-row ${inv.status === "Ödendi" ? "paid" : d != null && d < 0 ? "late" : ""}`} key={inv.id} data-testid={`invoice-row-${idx}`}>
            <div className="invoice-main"><b>{inv.supplier}</b><small className="muted">{inv.invoice_no ? `No ${inv.invoice_no} · ` : ""}{trDate(inv.date)}{inv.due_date ? ` · vade ${trDate(inv.due_date)}` : ""} · {inv.category}</small>{inv.note && <small className="muted">{inv.note}</small>}<InvoiceFiles invoice={inv} onChange={onReload} /></div>
            <div className="invoice-money"><strong>{money(inv.amount)}</strong><small className="muted">KDV %{inv.vat_rate} · {money(inv.amount - inv.amount / (1 + inv.vat_rate / 100))}</small>{due}</div>
            <div className="invoice-actions">
              {inv.status === "Ödenmedi" ? <button className="primary-button" data-testid={`invoice-pay-button-${idx}`} onClick={() => setPaying(inv)}><CheckCircle2 size={14} /> Öde</button> : <button className="secondary-button" data-testid={`invoice-unpay-button-${idx}`} onClick={() => unpay(inv)}><RotateCcw size={13} /> Geri al</button>}
              <button className="text-button tiny" data-testid={`invoice-edit-${idx}`} onClick={() => onEdit("invoices", inv)}>Düzenle</button>
              <button className="text-button tiny danger-inline" data-testid={`invoice-delete-${idx}`} onClick={() => window.confirm(inv.expense_id ? "Fatura ve bağlı gider kaydı silinsin mi?" : "Fatura silinsin mi?") && onDelete("invoices", inv.id)}><Trash2 size={11} /> Sil</button>
            </div>
          </div>
        );
      })}
      {paying && <PayDialog invoice={paying} onClose={() => setPaying(null)} onDone={onReload} />}
    </>
  );
}

export const CashBook = ({ data, onAdd, onEdit, onDelete, onReload }) => {
  const [tab, setTab] = useState("incomes");
  const tabs = [["incomes", "Gelirler", data.incomes.length], ["expenses", "Giderler", data.expenses_list.length], ["invoices", "Faturalar", data.invoices.filter((i) => i.status === "Ödenmedi").length]];
  return (
    <section className="panel table-panel cash-book" data-testid="cash-book">
      <div className="panel-head"><div><h3>Manuel kayıtlar</h3><span className="muted">POS'unuzdaki ciroyu, giderleri ve faturaları buraya girin; kasa hesabı ve raporlar otomatik güncellenir</span></div></div>
      <div className="book-tabs">{tabs.map(([k, l, n]) => <button key={k} className={tab === k ? "active" : ""} data-testid={`cash-book-tab-${k}`} onClick={() => setTab(k)}>{l}{n > 0 && <span>{n}</span>}</button>)}</div>
      {tab === "incomes" && <IncomeList items={data.incomes} onAdd={onAdd} onEdit={onEdit} onDelete={onDelete} />}
      {tab === "expenses" && <ExpenseList items={data.expenses_list} onAdd={onAdd} onEdit={onEdit} onDelete={onDelete} />}
      {tab === "invoices" && <InvoiceList items={data.invoices} onAdd={onAdd} onEdit={onEdit} onDelete={onDelete} onReload={onReload} />}
    </section>
  );
};
