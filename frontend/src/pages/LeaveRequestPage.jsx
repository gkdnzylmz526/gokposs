import { useEffect, useState } from "react";
import axios from "axios";
import { CalendarCheck, Send } from "lucide-react";
import { Toaster, toast } from "sonner";
import { DatePicker } from "@/components/DatePicker";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const fmt = (d) => new Date(`${d}T12:00:00`).toLocaleDateString("tr-TR", { day: "numeric", month: "long" });
const statusClass = { Bekliyor: "pending", "Onaylandı": "approved", Reddedildi: "rejected" };

export default function LeaveRequestPage({ token }) {
  const [info, setInfo] = useState(null);
  const [error, setError] = useState("");
  const [form, setForm] = useState({ start: "", end: "", type: "Yıllık izin", note: "" });
  const [sending, setSending] = useState(false);
  const load = () => axios.get(`${API}/public/leave/${token}`).then(({ data }) => setInfo(data)).catch((e) => setError(e.response?.data?.detail || "Sayfa yüklenemedi"));
  useEffect(() => { load(); }, [token]); // eslint-disable-line react-hooks/exhaustive-deps
  const submit = async () => {
    if (!form.start || !form.end) return toast.error("Başlangıç ve bitiş tarihini seçin");
    setSending(true);
    try { await axios.post(`${API}/public/leave/${token}`, form); toast.success("Talebiniz yöneticiye iletildi"); setForm({ start: "", end: "", type: "Yıllık izin", note: "" }); load(); }
    catch (e) { const d = e.response?.data?.detail; toast.error(typeof d === "string" ? d : "Talep gönderilemedi"); }
    finally { setSending(false); }
  };
  return (
    <div className="public-page" data-testid="leave-request-page">
      <Toaster richColors position="top-center" />
      <div className="public-card">
        <div className="brand public-brand"><div className="brand-mark">G</div><div><strong>GÖKBOSS POS</strong><span>İzin talebi</span></div></div>
        {error ? <div className="empty-state" data-testid="leave-request-error">{error}</div> : !info ? <div className="empty-state">Yükleniyor…</div> : (
          <>
            <h1 data-testid="leave-request-name">Merhaba {info.name}</h1>
            <div className="public-balance" data-testid="leave-request-balance"><CalendarCheck size={18} /> Yıllık izin hakkınız: <b>{info.balance.remaining} / {info.balance.total} gün</b> kaldı</div>
            <div className="form-grid">
              <div className="public-dates">
                <DatePicker label="Başlangıç" testId="leave-request-start" value={form.start} min={new Date(Date.now() - 7 * 864e5).toLocaleDateString("sv-SE")} max={form.end} onChange={(v) => setForm({ ...form, start: v })} />
                <DatePicker label="Bitiş" testId="leave-request-end" value={form.end} min={form.start || new Date(Date.now() - 7 * 864e5).toLocaleDateString("sv-SE")} onChange={(v) => setForm({ ...form, end: v })} />
              </div>
              <label>İzin türü<select value={form.type} data-testid="leave-request-type" onChange={(e) => setForm({ ...form, type: e.target.value })}>{info.types.map((t) => <option key={t}>{t}</option>)}</select></label>
              <label>Not (isteğe bağlı)<input value={form.note} maxLength={300} data-testid="leave-request-note" placeholder="örn. aile ziyareti" onChange={(e) => setForm({ ...form, note: e.target.value })} /></label>
            </div>
            <button className="primary-button full" data-testid="leave-request-submit" disabled={sending} onClick={submit}><Send size={16} /> {sending ? "Gönderiliyor…" : "Talebi gönder"}</button>
            <h3 className="public-subtitle">Taleplerim</h3>
            {!info.requests.length && <div className="empty-state small">Henüz talebiniz yok.</div>}
            {info.requests.map((r, i) => (
              <div className="public-request" key={r.id} data-testid={`leave-request-item-${i}`}>
                <span><b>{fmt(r.start)}{r.end !== r.start ? ` – ${fmt(r.end)}` : ""}</b><small>{r.type} · {r.days} gün</small></span>
                <em className={`req-status ${statusClass[r.status]}`}>{r.status}</em>
              </div>
            ))}
          </>
        )}
      </div>
    </div>
  );
}
