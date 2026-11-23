import { useEffect, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { UserButton } from "@clerk/react";
import { Boxes, Minus, Plus, ReceiptText, Save } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

function SalesEntry({ products, onSaved }) {
  const [cart, setCart] = useState({});
  const [channel, setChannel] = useState("Salon");
  const [saving, setSaving] = useState(false);
  const change = (id, d) => setCart((c) => ({ ...c, [id]: Math.max(0, (c[id] || 0) + d) }));
  const items = Object.entries(cart).filter(([, q]) => q > 0);
  const submit = async () => {
    setSaving(true);
    try {
      for (const [id, quantity] of items) await axios.post(`${API}/sales`, { product_id: id, product_name: products.find((p) => p.id === id)?.name, quantity, channel });
      toast.success(`${items.length} satış kaydedildi`); setCart({}); onSaved();
    } catch (e) { toast.error(e.response?.data?.detail || "Satış kaydedilemedi"); } finally { setSaving(false); }
  };
  return (
    <section data-testid="staff-sales">
      <div className="staff-channels">{["Salon", "Paket", "Online"].map((c) => <button key={c} className={`report-tab ${channel === c ? "active" : ""}`} data-testid={`staff-channel-${c}`} onClick={() => setChannel(c)}>{c}</button>)}</div>
      {!products.length && <div className="empty-state">Menüde ürün yok. Yöneticinizden ürün eklemesini isteyin.</div>}
      <div className="staff-products">
        {products.filter((p) => p.active !== false).map((p) => (
          <div key={p.id} className={`staff-product ${cart[p.id] ? "picked" : ""}`} data-testid={`staff-product-${p.id}`}>
            <button className="staff-product-main" onClick={() => change(p.id, 1)}><b>{p.name}</b><small>{p.category}</small></button>
            <div className="staff-qty"><button data-testid={`staff-minus-${p.id}`} onClick={() => change(p.id, -1)}><Minus size={14} /></button><span data-testid={`staff-qty-${p.id}`}>{cart[p.id] || 0}</span><button data-testid={`staff-plus-${p.id}`} onClick={() => change(p.id, 1)}><Plus size={14} /></button></div>
          </div>
        ))}
      </div>
      <button className="primary-button full staff-submit" data-testid="staff-sales-submit" disabled={!items.length || saving} onClick={submit}><ReceiptText size={17} /> {saving ? "Kaydediliyor…" : `Satışı kaydet (${items.reduce((s, [, q]) => s + q, 0)} adet)`}</button>
    </section>
  );
}

function StockCount({ inventory, onSaved }) {
  const [counts, setCounts] = useState({});
  const save = async (item) => {
    try { await axios.post(`${API}/inventory/${item.id}/count`, { quantity: Number(counts[item.id]) }); toast.success(`${item.name} sayımı kaydedildi`); setCounts((c) => ({ ...c, [item.id]: undefined })); onSaved(); }
    catch { toast.error("Sayım kaydedilemedi"); }
  };
  return (
    <section className="staff-stock" data-testid="staff-stock">
      {!inventory.length && <div className="empty-state">Stok kalemi yok.</div>}
      {inventory.map((i) => (
        <div key={i.id} className={`staff-stock-row ${i.quantity <= i.minimum ? "low" : ""}`} data-testid={`staff-stock-row-${i.id}`}>
          <span><b>{i.name}</b><small>Kayıtlı: {Number(i.quantity).toLocaleString("tr-TR")} {i.unit}</small></span>
          <input type="number" inputMode="decimal" step="any" min="0" placeholder="Sayılan" value={counts[i.id] ?? ""} data-testid={`staff-count-input-${i.id}`} onChange={(e) => setCounts({ ...counts, [i.id]: e.target.value })} />
          <button className="secondary-button" data-testid={`staff-count-save-${i.id}`} disabled={counts[i.id] === undefined || counts[i.id] === ""} onClick={() => save(i)}><Save size={14} /></button>
        </div>
      ))}
    </section>
  );
}

export default function StaffApp() {
  const [tab, setTab] = useState("sales");
  const [data, setData] = useState({ products: [], inventory: [] });
  const load = () => axios.get(`${API}/staff-view`).then(({ data: d }) => setData(d)).catch(() => toast.error("Veriler yüklenemedi"));
  useEffect(() => { load(); }, []);
  return (
    <div className="staff-app" data-testid="staff-app">
      <header className="staff-header"><div className="brand"><div className="brand-mark">G</div><div><strong>GÖKBOSS POS</strong><span>Personel</span></div></div><UserButton /></header>
      <nav className="staff-tabs">
        <button className={tab === "sales" ? "active" : ""} data-testid="staff-tab-sales" onClick={() => setTab("sales")}><ReceiptText size={16} /> Satış gir</button>
        <button className={tab === "stock" ? "active" : ""} data-testid="staff-tab-stock" onClick={() => setTab("stock")}><Boxes size={16} /> Stok sayımı</button>
      </nav>
      <main className="staff-main">{tab === "sales" ? <SalesEntry products={data.products} onSaved={load} /> : <StockCount inventory={data.inventory} onSaved={load} />}</main>
    </div>
  );
}
