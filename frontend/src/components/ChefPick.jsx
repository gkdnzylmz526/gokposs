import { useEffect, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { ChefHat, X } from "lucide-react";
import { errorText } from "@/lib/restaurant";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export const ChefPickCard = ({ products }) => {
  const [pick, setPick] = useState(null);
  const [productId, setProductId] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const active = (products || []).filter((p) => p.active !== false);
  useEffect(() => { axios.get(`${API}/chef-pick`).then(({ data }) => { setPick(data); if (data.today) { setProductId(data.product_id); setNote(data.note); } }).catch(() => setPick({})); }, []);
  const save = async () => {
    if (!productId) return toast.error("Bir ürün seçin");
    setBusy(true);
    try { const { data } = await axios.put(`${API}/chef-pick`, { product_id: productId, note }); setPick(data); toast.success("Günün önerisi QR menüde yayında"); }
    catch (e) { toast.error(errorText(e, "Kaydedilemedi")); } finally { setBusy(false); }
  };
  const clear = async () => {
    try { await axios.delete(`${API}/chef-pick`); setPick({}); setProductId(""); setNote(""); toast.success("Günün önerisi kaldırıldı"); }
    catch (e) { toast.error(errorText(e, "Kaldırılamadı")); }
  };
  const live = pick?.today && active.find((p) => p.id === pick.product_id);
  return (
    <section className="panel chef-pick-card" data-testid="chef-pick-card">
      <div className="chef-pick-head">
        <div className="chef-pick-icon"><ChefHat size={20} /></div>
        <div><h3>Günün önerisi</h3><span className="muted" data-testid="chef-pick-status">{live ? `Bugün QR menüde: ${live.name}` : "Bugün için seçilmedi. Her sabah seçin; gece yarısı kendiliğinden kalkar."}</span></div>
        {live && <button className="text-button danger-text" onClick={clear} data-testid="chef-pick-clear"><X size={14} /> Kaldır</button>}
      </div>
      <div className="chef-pick-form">
        <select value={productId} onChange={(e) => setProductId(e.target.value)} data-testid="chef-pick-select"><option value="">Ürün seçin</option>{active.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
        <input value={note} maxLength={120} onChange={(e) => setNote(e.target.value)} placeholder="Kısa not (isteğe bağlı) — örn. bugün taze kuzu etiyle" data-testid="chef-pick-note" />
        <button className="primary-button" disabled={busy} onClick={save} data-testid="chef-pick-save">{busy ? "Kaydediliyor…" : live ? "Güncelle" : "Bugün için seç"}</button>
      </div>
    </section>
  );
};
