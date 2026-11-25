import { useEffect, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Archive, KeyRound, Mail, Pencil, Plus, RotateCcw, Store } from "lucide-react";
import { errorText } from "@/lib/restaurant";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const blank = { name: "", email: "", pin: "" };

function RestaurantForm({ item, onClose, onSaved }) {
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
      {item?.has_pin && <label className="rest-check"><input type="checkbox" checked={clearPin} onChange={(e) => setClearPin(e.target.checked)} data-testid="restaurant-form-clear-pin" /> Şifreyi kaldır</label>}
      <div className="rest-form-actions"><button type="button" className="text-button" onClick={onClose} data-testid="restaurant-form-cancel">Vazgeç</button><button className="primary-button" data-testid="restaurant-form-save">Kaydet</button></div>
    </form>
  );
}

function RestaurantRow({ r, onEdit, onToggle }) {
  return (
    <div className={`rest-row ${r.archived ? "archived" : ""}`} data-testid={`restaurant-row-${r.id}`}>
      <Store size={18} />
      <div><b>{r.name}</b><small>{r.email ? <><Mail size={11} /> {r.email}</> : "E-posta yok"} · {r.has_pin ? <><KeyRound size={11} /> Şifreli</> : "Şifresiz"}{r.archived && " · Arşivde"}</small></div>
      {!r.archived && <button className="text-button" onClick={onEdit} data-testid={`restaurant-edit-${r.id}`}><Pencil size={14} /> Düzenle</button>}
      <button className={`text-button ${r.archived ? "" : "danger-text"}`} onClick={onToggle} data-testid={`restaurant-${r.archived ? "restore" : "archive"}-${r.id}`}>{r.archived ? <><RotateCcw size={14} /> Geri al</> : <><Archive size={14} /> Sil</>}</button>
    </div>
  );
}

export const RestaurantAdmin = ({ onChanged }) => {
  const [rows, setRows] = useState([]);
  const [editing, setEditing] = useState(null);
  const load = () => axios.get(`${API}/restaurants/manage`).then(({ data }) => setRows(data)).catch(() => toast.error("Restoranlar yüklenemedi"));
  useEffect(() => { load(); }, []);
  const done = () => { setEditing(null); load(); onChanged(); };
  const toggle = async (r) => {
    if (!r.archived && !window.confirm(`${r.name} silinsin mi?\n\nRestoran arşive kaldırılır, kayıtları silinmez ve istediğiniz zaman geri alabilirsiniz.`)) return;
    try { await axios.post(`${API}/restaurants/manage/${r.id}/${r.archived ? "restore" : "archive"}`); toast.success(r.archived ? "Restoran geri alındı" : "Restoran arşive kaldırıldı"); done(); }
    catch (err) { toast.error(errorText(err, "İşlem yapılamadı")); }
  };
  return (
    <section className="panel rest-admin" data-testid="restaurant-admin">
      <div className="panel-head"><div><h3>Restoranlar</h3><span className="muted">Ekle, sil, şifre ve restoran e-postası belirle</span></div>{editing === null && <button className="primary-button" onClick={() => setEditing("new")} data-testid="restaurant-add-button"><Plus size={15} /> Restoran ekle</button>}</div>
      {editing && <RestaurantForm item={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={done} />}
      {rows.map((r) => <RestaurantRow key={r.id} r={r} onEdit={() => setEditing(r)} onToggle={() => toggle(r)} />)}
    </section>
  );
};
