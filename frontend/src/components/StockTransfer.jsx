import { useEffect, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { ArrowRightLeft, Plus, Trash2, X } from "lucide-react";
import { RESTAURANTS, errorText } from "@/lib/restaurant";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const money = (n) => new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY", maximumFractionDigits: 2 }).format(n || 0);

function TransferDialog({ rid, inventory, onClose, onDone }) {
  const targets = RESTAURANTS.filter((r) => r.id !== rid);
  const [to, setTo] = useState(targets[0].id);
  const [rows, setRows] = useState([{ inventory_id: "", quantity: "" }]);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const update = (i, patch) => setRows(rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  const items = rows.filter((r) => r.inventory_id && Number(r.quantity) > 0).map((r) => ({ inventory_id: r.inventory_id, quantity: Number(r.quantity) }));
  const save = async () => { setBusy(true); try { await axios.post(`${API}/stock-transfers`, { to_restaurant: to, items, note }); toast.success("Transfer kaydedildi, iki restoranın stoğu güncellendi"); onDone(); onClose(); } catch (e) { toast.error(errorText(e, "Transfer yapılamadı")); } finally { setBusy(false); } };
  return (
    <div className="modal-backdrop">
      <div className="modal" data-testid="transfer-dialog">
        <button className="icon-button close" data-testid="transfer-close" onClick={onClose}><X size={18} /></button>
        <span className="eyebrow">STOK TRANSFERİ</span>
        <h2>Başka restorana gönder</h2>
        <div className="form-grid">
          <label>Hedef restoran<select value={to} onChange={(e) => setTo(e.target.value)} data-testid="transfer-target-select">{targets.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}</select></label>
          <div className="recipe-editor">
            <span className="recipe-title">Gönderilen malzemeler (bu restorandan düşer, hedefte aynı isimli malzemeye eklenir; yoksa oluşturulur)</span>
            {rows.map((r, i) => { const item = inventory.find((x) => x.id === r.inventory_id); return (
              <div className="purchase-row" key={i} data-testid={`transfer-row-${i}`}>
                <select value={r.inventory_id} data-testid={`transfer-ingredient-${i}`} onChange={(e) => update(i, { inventory_id: e.target.value })}><option value="">Malzeme seçin</option>{inventory.map((x) => <option key={x.id} value={x.id}>{x.name} ({Number(x.quantity).toLocaleString("tr-TR")} {x.unit})</option>)}</select>
                <input type="number" step="any" min="0" placeholder={item ? `en fazla ${item.quantity} ${item.unit}` : "Miktar"} value={r.quantity} data-testid={`transfer-quantity-${i}`} onChange={(e) => update(i, { quantity: e.target.value })} />
                <button type="button" className="icon-button" data-testid={`transfer-remove-${i}`} onClick={() => setRows(rows.filter((_, idx) => idx !== i))}><Trash2 size={14} /></button>
              </div>); })}
            <button type="button" className="text-button" data-testid="transfer-add-row" onClick={() => setRows([...rows, { inventory_id: "", quantity: "" }])}>+ Malzeme ekle</button>
          </div>
          <label>Not<input value={note} onChange={(e) => setNote(e.target.value)} placeholder="örn. hafta sonu takviyesi" data-testid="transfer-note" /></label>
        </div>
        <button className="primary-button full" disabled={busy || !items.length} data-testid="transfer-save" onClick={save}><ArrowRightLeft size={16} /> Transferi kaydet</button>
      </div>
    </div>
  );
}

export const StockTransfers = ({ rid, inventory, refreshKey, onReload }) => {
  const [list, setList] = useState([]);
  const [open, setOpen] = useState(false);
  useEffect(() => { axios.get(`${API}/stock-transfers`).then(({ data }) => setList(data)).catch(() => setList([])); }, [refreshKey]);
  const undo = async (t) => { if (!window.confirm("Transfer geri alınsın mı? Malzemeler hedef restorandan geri düşülür.")) return; try { await axios.delete(`${API}/stock-transfers/${t.id}`); toast.success("Transfer geri alındı"); onReload(); } catch (e) { toast.error(errorText(e, "Geri alınamadı")); } };
  const grid = { gridTemplateColumns: "1fr 1.4fr 2fr .9fr 60px" };
  return (
    <section className="panel table-panel transfer-panel" data-testid="stock-transfers">
      <div className="panel-head movements-head">
        <div><h3><ArrowRightLeft size={17} /> Restoranlar arası transfer</h3><span className="muted">Bir restorandan diğerine gönderilen malzemeler iki stokta da otomatik işlenir</span></div>
        <button className="primary-button" disabled={rid === "all"} data-testid="transfer-open-button" onClick={() => setOpen(true)}><Plus size={15} /> Transfer yap</button>
      </div>
      <div className="table-head" style={grid}><span>Tarih</span><span>Yön</span><span>Malzemeler</span><span>Değer</span><span /></div>
      {!list.length && <div className="empty-state">Henüz transfer yok.</div>}
      {list.map((t, i) => (
        <div className="table-row" style={grid} key={t.id} data-testid={`transfer-row-hist-${i}`}>
          <span>{new Date(t.created_at).toLocaleString("tr-TR", { dateStyle: "short", timeStyle: "short" })}</span>
          <span><b className={t.from_restaurant === rid ? "danger-inline" : "green-text"}>{t.from_restaurant === rid ? "Giden" : t.to_restaurant === rid ? "Gelen" : ""}</b> {t.from_name} → {t.to_name}</span>
          <span>{t.items.map((x) => `${Number(x.quantity).toLocaleString("tr-TR")} ${x.unit} ${x.name}`).join(", ")}{t.note ? <small className="muted block">{t.note}</small> : null}</span>
          <span className="table-amount">{money(t.value)}</span>
          <span>{t.from_restaurant === rid && <button className="text-button tiny danger-inline" data-testid={`transfer-undo-${i}`} onClick={() => undo(t)}>Geri al</button>}</span>
        </div>
      ))}
      {open && <TransferDialog rid={rid} inventory={inventory} onClose={() => setOpen(false)} onDone={onReload} />}
    </section>
  );
};
