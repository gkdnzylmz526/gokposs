import { useMemo, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Save, Trash2 } from "lucide-react";
import { errorText } from "@/lib/restaurant";
import { DatePicker } from "@/components/DatePicker";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const money = (n) => new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY", maximumFractionDigits: 2 }).format(n || 0);
const today = () => new Date().toLocaleDateString("sv-SE");
const trDate = (d) => new Date(`${d}T12:00:00`).toLocaleDateString("tr-TR", { day: "2-digit", month: "long", weekday: "short" });
const LINES = [
  { key: "nakit", label: "Nakit", payment: "Nakit", category: "POS satış" },
  { key: "kart", label: "Kredi kartı", payment: "Kart", category: "POS satış" },
  { key: "yemek", label: "Yemek kartı", payment: "Yemek kartı", category: "POS satış" },
  { key: "havale", label: "Havale / EFT", payment: "Havale", category: "Diğer" },
  { key: "ys", label: "Yemeksepeti", payment: "Kart", category: "Yemeksepeti" },
  { key: "getir", label: "Getir", payment: "Kart", category: "Getir" },
  { key: "trendyol", label: "Trendyol Yemek", payment: "Kart", category: "Trendyol Yemek" },
];

function DayList({ incomes, onDelete }) {
  const days = useMemo(() => {
    const map = {};
    incomes.forEach((i) => { (map[i.date] ||= []).push(i); });
    return Object.entries(map).sort((a, b) => b[0].localeCompare(a[0])).slice(0, 31);
  }, [incomes]);
  if (!days.length) return <div className="empty-state">Henüz ciro girilmedi.</div>;
  return days.map(([date, items], idx) => (
    <div className="rev-day" key={date} data-testid={`revenue-day-${idx}`}>
      <div className="rev-day-head"><b>{trDate(date)}</b><strong className="green-text" data-testid={`revenue-day-total-${idx}`}>{money(items.reduce((s, i) => s + i.amount, 0))}</strong></div>
      <div className="rev-chips">{items.map((i) => <span className="rev-chip" key={i.id}>{i.category === "POS satış" ? i.payment : i.category}: {money(i.amount)}<button aria-label="Sil" data-testid={`revenue-delete-${i.id}`} onClick={() => onDelete("incomes", i.id)}><Trash2 size={12} /></button></span>)}</div>
    </div>
  ));
}

export function RevenueEntry({ incomes, onReload, onDelete }) {
  const [date, setDate] = useState(today());
  const [vals, setVals] = useState({});
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const total = LINES.reduce((s, l) => s + (parseFloat(vals[l.key]) || 0), 0);
  const save = async () => {
    const rows = LINES.filter((l) => parseFloat(vals[l.key]) > 0);
    if (!rows.length) return toast.error("En az bir tutar girin");
    setSaving(true);
    try {
      for (const l of rows) await axios.post(`${API}/incomes`, { amount: parseFloat(vals[l.key]), date, payment: l.payment, category: l.category, note: note || "Manuel ciro girişi" });
      toast.success(`${money(total)} ciro kaydedildi`);
      setVals({}); setNote(""); onReload();
    } catch (e) { toast.error(errorText(e, "Ciro kaydedilemedi")); } finally { setSaving(false); }
  };
  return <>
    <div className="welcome-row"><div><p className="eyebrow">MANUEL CİRO</p><h2>Ciro Girişi</h2><p className="muted">POS'unuzdaki gün sonu tutarlarını buraya yazın; raporlar ve maliyet hesabı bu rakamlarla çalışır.</p></div></div>
    <section className="panel rev-form" data-testid="revenue-form">
      <div className="rev-date"><span>Tarih</span><DatePicker value={date} onChange={setDate} testId="revenue-date" /></div>
      <div className="rev-grid">{LINES.map((l) => <label key={l.key} className="rev-field"><span>{l.label}</span><input type="number" inputMode="decimal" min="0" placeholder="0" value={vals[l.key] || ""} onChange={(e) => setVals({ ...vals, [l.key]: e.target.value })} data-testid={`revenue-input-${l.key}`} /></label>)}</div>
      <label className="rev-field rev-note"><span>Not (isteğe bağlı)</span><input value={note} placeholder="örn. Z raporu" onChange={(e) => setNote(e.target.value)} data-testid="revenue-note" /></label>
      <div className="rev-foot"><div><span className="muted">Toplam</span><strong data-testid="revenue-form-total">{money(total)}</strong></div><button className="primary-button" disabled={saving} onClick={save} data-testid="revenue-save-button"><Save size={16} /> {saving ? "Kaydediliyor…" : "Ciroyu kaydet"}</button></div>
    </section>
    <section className="panel"><div className="panel-head"><div><h3>Girilen cirolar</h3><span className="muted">Son 31 gün, güne göre</span></div></div><DayList incomes={incomes} onDelete={onDelete} /></section>
  </>;
}
