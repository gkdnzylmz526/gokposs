import { useEffect, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Archive, Check, KeyRound, Mail, Pencil, Plus, RotateCcw, Store, X } from "lucide-react";
import { RestaurantImages, imageUrl } from "@/components/RestaurantImages";
import { errorText } from "@/lib/restaurant";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const blank = { name: "", email: "", pin: "" };

function RestaurantForm({ item, onClose, onSaved, onImages }) {
  const [form, setForm] = useState(item ? { name: item.name, email: item.email, pin: "" } : blank);
  const [clearPin, setClearPin] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: k === "pin" ? e.target.value.replace(/\D/g, "") : e.target.value });
  const save = async (e) => {
    e.preventDefault();
    try {
      if (item) await axios.patch(`${API}/restaurants/manage/${item.id}`, { name: form.name, email: form.email, ...(form.pin ? { pin: form.pin } : clearPin ? { pin: "" } : {}) });
      else await axios.post(`${API}/restaurants/manage`, form);
      toast.success(item ? "Restoran güncellendi" : "Restoran eklendi"); onSaved();
    } catch (err) { toast.error(errorText(err, "Kaydedilemedi")); }
  };
  return (
    <form className="rest-form" onSubmit={save} data-testid="restaurant-form">
      <label><span>Restoran adı</span><input required value={form.name} onChange={set("name")} placeholder="örn. Bakırköy Şube" data-testid="restaurant-form-name" /></label>
      <label><span>Restoran e-postası (bu e-postayla giren sadece bu restoranı görür)</span><input type="email" value={form.email} onChange={set("email")} placeholder="sube@ornek.com" data-testid="restaurant-form-email" /></label>
      <label><span>{item?.has_pin ? "Yeni şifre (boş bırakılırsa değişmez)" : "Şifre (4-6 rakam, boşsa şifresiz)"}</span><input type="password" inputMode="numeric" maxLength={6} value={form.pin} onChange={set("pin")} placeholder="••••" data-testid="restaurant-form-pin" /></label>
      {item && <RestaurantImages item={item} onChange={onImages} />}
      {item?.has_pin && <label className="rest-check"><input type="checkbox" checked={clearPin} onChange={(e) => setClearPin(e.target.checked)} data-testid="restaurant-form-clear-pin" /> Şifreyi kaldır</label>}
      <div className="rest-form-actions"><button type="button" className="text-button" onClick={onClose} data-testid="restaurant-form-cancel">Vazgeç</button><button className="primary-button" data-testid="restaurant-form-save">Kaydet</button></div>
    </form>
  );
}

function RestaurantRow({ r, onEdit, onToggle }) {
  return (
    <div className={`rest-row ${r.archived ? "archived" : ""}`} data-testid={`restaurant-row-${r.id}`}>
      {r.logo_id ? <img className="rest-logo-thumb" src={imageUrl(r.logo_id)} alt="" /> : <Store size={18} />}
      <div><b>{r.name}</b><small>{r.email ? <><Mail size={11} /> {r.email}</> : "E-posta yok"} · {r.has_pin ? <><KeyRound size={11} /> Şifreli</> : "Şifresiz"}{r.archived && " · Arşivde"}</small></div>
      {!r.archived && <button className="text-button" onClick={onEdit} data-testid={`restaurant-edit-${r.id}`}><Pencil size={14} /> Düzenle</button>}
      <button className={`text-button ${r.archived ? "" : "danger-text"}`} onClick={onToggle} data-testid={`restaurant-${r.archived ? "restore" : "archive"}-${r.id}`}>{r.archived ? <><RotateCcw size={14} /> Geri al</> : <><Archive size={14} /> Sil</>}</button>
    </div>
  );
}

export const RestaurantAdmin = ({ onChanged }) => {
  const [rows, setRows] = useState([]);
  const [editing, setEditing] = useState(null);
  const [showArchive, setShowArchive] = useState(false);
  const archived = rows.filter((r) => r.archived);
  const [requests, setRequests] = useState([]);
  const load = () => { axios.get(`${API}/restaurants/manage`).then(({ data }) => { setRows(data); setEditing((e) => (e && e !== "new" ? data.find((r) => r.id === e.id) || null : e)); }).catch(() => toast.error("Restoranlar yüklenemedi")); axios.get(`${API}/restaurants/manage/pin-requests`).then(({ data }) => setRequests(data)).catch(() => setRequests([])); };
  useEffect(() => { load(); }, []);
  const decide = async (req, decision) => {
    try { await axios.post(`${API}/restaurants/manage/pin-requests/${req.id}/${decision}`); toast.success(decision === "approve" ? `${req.restaurant_name} şifresi değişti` : "Talep reddedildi"); done(); }
    catch (err) { toast.error(errorText(err, "İşlem yapılamadı")); }
  };
  const done = () => { setEditing(null); load(); onChanged(); };
  const toggle = async (r) => {
    if (!r.archived && !window.confirm(`${r.name} silinsin mi?\n\nRestoran arşive kaldırılır, kayıtları silinmez ve istediğiniz zaman geri alabilirsiniz.`)) return;
    try { await axios.post(`${API}/restaurants/manage/${r.id}/${r.archived ? "restore" : "archive"}`); toast.success(r.archived ? "Restoran geri alındı" : "Restoran arşive kaldırıldı"); done(); }
    catch (err) { toast.error(errorText(err, "İşlem yapılamadı")); }
  };
  return (
    <section className="panel rest-admin" data-testid="restaurant-admin">
      <div className="panel-head"><div><h3>Restoranlar</h3><span className="muted">Ekle, sil, şifre ve restoran e-postası belirle</span></div>{editing === null && <button className="primary-button" onClick={() => setEditing("new")} data-testid="restaurant-add-button"><Plus size={15} /> Restoran ekle</button>}</div>
      {requests.map((q) => (
        <div className="pin-request" key={q.id} data-testid={`pin-request-${q.id}`}>
          <KeyRound size={16} /><div><b>{q.restaurant_name} için yeni şifre talebi</b><small>{q.user_email} · {new Date(q.created_at).toLocaleString("tr-TR", { dateStyle: "short", timeStyle: "short" })}</small></div>
          <button className="primary-button" onClick={() => decide(q, "approve")} data-testid={`pin-request-approve-${q.id}`}><Check size={14} /> Onayla</button>
          <button className="text-button danger-text" onClick={() => decide(q, "reject")} data-testid={`pin-request-reject-${q.id}`}><X size={14} /> Reddet</button>
        </div>
      ))}
      {editing && <RestaurantForm key={editing === "new" ? "new" : editing.id} item={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={done} onImages={() => { load(); onChanged(); }} />}
      {rows.filter((r) => !r.archived).map((r) => <RestaurantRow key={r.id} r={r} onEdit={() => setEditing(r)} onToggle={() => toggle(r)} />)}
      {archived.length > 0 && <button className="text-button rest-archive-toggle" onClick={() => setShowArchive(!showArchive)} data-testid="restaurant-archive-toggle"><Archive size={14} /> Arşiv ({archived.length}) {showArchive ? "gizle" : "göster"}</button>}
      {showArchive && archived.map((r) => <RestaurantRow key={r.id} r={r} onEdit={() => setEditing(r)} onToggle={() => toggle(r)} />)}
    </section>
  );
};
