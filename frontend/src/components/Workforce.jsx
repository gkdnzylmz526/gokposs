import { useEffect, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Clock, HandCoins, LogIn, LogOut, Trash2 } from "lucide-react";
import { DatePicker } from "@/components/DatePicker";
import { errorText } from "@/lib/restaurant";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const money = (n) => new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY", maximumFractionDigits: 2 }).format(n || 0);
const today = () => new Date().toLocaleDateString("sv-SE");
const hours = (a) => { if (!a.end) return null; const [sh, sm] = a.start.split(":").map(Number); const [eh, em] = a.end.split(":").map(Number); let m = eh * 60 + em - sh * 60 - sm; if (m < 0) m += 1440; return m / 60; };

export const TipsPanel = ({ refreshKey, onAdd, onDelete }) => {
  const [date, setDate] = useState(today());
  const [data, setData] = useState(null);
  useEffect(() => { axios.get(`${API}/tips/distribution`, { params: { date } }).then(({ data: d }) => setData(d)).catch(() => setData(null)); }, [date, refreshKey]);
  return (
    <section className="panel table-panel tips-panel" data-testid="tips-panel">
      <div className="panel-head movements-head">
        <div><h3><HandCoins size={17} /> Bahşiş dağıtımı</h3><span className="muted">Günün bahşişleri çalışılan saate göre paylaştırılır (giriş-çıkış varsa o, yoksa vardiya planı)</span></div>
        <div className="movements-filter"><DatePicker label="" testId="tips-date" value={date} onChange={(v) => setDate(v || today())} /><button className="primary-button" data-testid="add-tip-button" onClick={() => onAdd("tips", { date })}>+ Bahşiş</button></div>
      </div>
      <div className="tips-total"><span>Toplam bahşiş</span><strong data-testid="tips-total">{money(data?.total)}</strong><small>{data?.total_hours || 0} saat çalışma</small></div>
      {data?.tips?.length > 0 && <div className="tip-chips">{data.tips.map((t, i) => <span key={t.id} className="tip-chip" data-testid={`tip-entry-${i}`}>{money(t.amount)}{t.note ? ` · ${t.note}` : ""}<button title="Sil" data-testid={`tip-delete-${i}`} onClick={() => window.confirm("Bahşiş kaydı silinsin mi?") && onDelete("tips", t.id)}><Trash2 size={11} /></button></span>)}</div>}
      <div className="table-head" style={{ gridTemplateColumns: "1.5fr 1fr 1fr 1fr" }}><span>Personel</span><span>Saat</span><span>Kaynak</span><span>Payı</span></div>
      {!data?.rows?.length && <div className="empty-state">Bu gün için çalışma saati yok. Vardiya planlayın veya personel giriş-çıkış yapsın.</div>}
      {data?.rows?.map((r, i) => <div className="table-row" style={{ gridTemplateColumns: "1.5fr 1fr 1fr 1fr" }} key={r.staff_id} data-testid={`tip-share-row-${i}`}><span><b>{r.name}</b></span><span>{r.hours.toLocaleString("tr-TR")} sa</span><span className="muted">{r.source}</span><span className="table-amount green-text" data-testid={`tip-share-${i}`}>{money(r.share)}</span></div>)}
    </section>
  );
};

export const AttendancePanel = ({ items, staff, onAdd, onEdit, onDelete }) => {
  const [person, setPerson] = useState("");
  const name = (id) => staff.find((s) => s.id === id)?.name || "—";
  const grid = { gridTemplateColumns: "1fr 1.3fr .8fr .8fr .8fr 70px" };
  return (
    <section className="panel table-panel attendance-panel" data-testid="attendance-panel">
      <div className="panel-head movements-head">
        <div><h3><Clock size={17} /> Puantaj (giriş-çıkış)</h3><span className="muted">Personel telefonundan giriş-çıkış yapar; bu saatler varsa maaş hesabında vardiya planı yerine kullanılır</span></div>
        <div className="movements-filter"><select value={person} onChange={(e) => setPerson(e.target.value)} data-testid="attendance-staff-select"><option value="">Personel seçin</option>{staff.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select><button className="secondary-button" disabled={!person} data-testid="attendance-add-button" onClick={() => onAdd("attendance", { staff_id: person, date: today(), start: "09:00", end: "17:00" })}>+ Manuel kayıt</button></div>
      </div>
      <div className="table-head" style={grid}><span>Tarih</span><span>Personel</span><span>Giriş</span><span>Çıkış</span><span>Süre</span><span /></div>
      {!items.length && <div className="empty-state">Henüz giriş-çıkış kaydı yok.</div>}
      {items.slice(0, 40).map((a, i) => <div className="table-row" style={grid} key={a.id} data-testid={`attendance-row-${i}`}><span>{new Date(`${a.date}T12:00:00`).toLocaleDateString("tr-TR")}</span><span>{name(a.staff_id)}</span><span>{a.start}</span><span>{a.end || <em className="status status-green">Çalışıyor</em>}</span><span>{hours(a) == null ? "—" : `${hours(a).toFixed(2).replace(".", ",")} sa`}</span><span className="row-mini-actions"><button className="text-button tiny" data-testid={`attendance-edit-${i}`} onClick={() => onEdit("attendance", a)}>Düzenle</button><button className="text-button tiny danger-inline" data-testid={`attendance-delete-${i}`} onClick={() => window.confirm("Kayıt silinsin mi?") && onDelete("attendance", a.id)}>Sil</button></span></div>)}
    </section>
  );
};

export const ClockCard = () => {
  const [me, setMe] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = () => axios.get(`${API}/attendance/me`).then(({ data }) => setMe(data)).catch(() => setMe({ linked: false }));
  useEffect(() => { load(); }, []);
  if (!me) return null;
  if (!me.linked) return <div className="clock-card muted-card" data-testid="clock-card-unlinked"><Clock size={18} /> Giriş-çıkış için hesabınızın bir personel kaydına bağlanması gerekiyor. Yöneticinize söyleyin.</div>;
  const clock = async () => { setBusy(true); try { const { data } = await axios.post(`${API}/attendance/clock`); toast.success(data.status === "in" ? `Giriş yapıldı · ${data.start}` : `Çıkış yapıldı · ${data.start}–${data.end}`); await load(); } catch (e) { toast.error(errorText(e, "Kaydedilemedi")); } finally { setBusy(false); } };
  return (
    <div className={`clock-card ${me.open ? "working" : ""}`} data-testid="clock-card">
      <div><b>{me.name}</b><small data-testid="clock-status">{me.open ? `${me.open.start}'dan beri çalışıyorsunuz` : `Bugün ${String(me.today_hours).replace(".", ",")} saat çalıştınız`}</small></div>
      <button className={me.open ? "secondary-button" : "primary-button"} disabled={busy} data-testid="clock-button" onClick={clock}>{me.open ? <><LogOut size={16} /> Çıkış yap</> : <><LogIn size={16} /> Giriş yap</>}</button>
    </div>
  );
};
