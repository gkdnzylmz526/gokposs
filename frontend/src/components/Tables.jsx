import { useCallback, useEffect, useMemo, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Armchair, ChefHat, Minus, Plus, Trash2, X } from "lucide-react";
import { PayBox } from "@/components/TablePay";
import { errorText } from "@/lib/restaurant";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const money = (n) => new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY", maximumFractionDigits: 2 }).format(n || 0);
const since = (iso) => { const m = Math.round((Date.now() - new Date(iso)) / 60000); return m < 60 ? `${m} dk` : `${Math.floor(m / 60)} sa ${m % 60} dk`; };

function ProductPicker({ products, onPick }) {
  const cats = useMemo(() => [...new Set(products.map((p) => p.category || "Genel"))], [products]);
  const [cat, setCat] = useState("");
  const shown = products.filter((p) => !cat || (p.category || "Genel") === cat);
  return (
    <div className="table-picker" data-testid="table-product-picker">
      <div className="staff-channels"><button className={`report-tab ${!cat ? "active" : ""}`} onClick={() => setCat("")} data-testid="table-cat-all">Tümü</button>{cats.map((c) => <button key={c} className={`report-tab ${cat === c ? "active" : ""}`} onClick={() => setCat(c)} data-testid={`table-cat-${c}`}>{c}</button>)}</div>
      <div className="table-picker-grid">{shown.map((p) => <button key={p.id} className="table-picker-item" data-testid={`table-add-product-${p.id}`} onClick={() => onPick(p.id, 1)}><b>{p.name}</b><small>{money(p.price)}</small></button>)}</div>
    </div>
  );
}

function OrderPanel({ table, products, onChange, onClose, onDone }) {
  const [busy, setBusy] = useState(false);
  const order = table.order;
  const call = async (fn, ok) => { setBusy(true); try { await fn(); if (ok) toast.success(ok); await onChange(); } catch (e) { toast.error(errorText(e, "İşlem yapılamadı")); } finally { setBusy(false); } };
  const add = (productId, quantity) => call(() => axios.post(`${API}/tables/${table.id}/items`, { product_id: productId, quantity }));
  const cancel = () => window.confirm("Açık hesap iptal edilsin mi? Satış kaydı oluşmaz.") && call(async () => { await axios.post(`${API}/tables/${table.id}/cancel`); onClose(); onDone?.(); }, "Hesap iptal edildi");
  const paid = async (closed) => { await onChange(); onDone?.(); if (closed) onClose(); };
  return (
    <div className="table-order" data-testid="table-order-panel">
      <div className="panel-head"><div><h3>Masa {table.name}</h3><span className="muted">{order ? `Açık · ${since(order.opened_at)}` : "Boş masa · ürün ekleyince hesap açılır ve mutfağa gider"}</span></div><button className="icon-button" data-testid="table-order-close" onClick={onClose}><X size={16} /></button></div>
      {table.ready_count > 0 && <div className="ready-note" data-testid="table-ready-note"><ChefHat size={14} /> Mutfakta {table.ready_count} sipariş hazır, servis edin</div>}
      <div className="table-order-items">
        {!order?.items?.length && <div className="empty-state">{order?.paid?.length ? "Kalan ürün yok." : "Henüz ürün yok."}</div>}
        {order?.items?.map((i) => (
          <div key={i.product_id} className="table-order-row" data-testid={`table-item-${i.product_id}`}>
            <span><b>{i.product_name}</b><small>{money(i.unit_price)}</small></span>
            <div className="staff-qty"><button disabled={busy} data-testid={`table-item-minus-${i.product_id}`} onClick={() => add(i.product_id, -1)}><Minus size={14} /></button><span data-testid={`table-item-qty-${i.product_id}`}>{Number(i.quantity).toLocaleString("tr-TR")}</span><button disabled={busy} data-testid={`table-item-plus-${i.product_id}`} onClick={() => add(i.product_id, 1)}><Plus size={14} /></button></div>
            <strong>{money(i.quantity * i.unit_price)}</strong>
          </div>
        ))}
      </div>
      <div className="table-order-total"><span>Hesap</span><strong data-testid="table-order-total">{money(order?.total)}</strong></div>
      {order?.items?.length > 0 && <PayBox key={order.id} table={table} onPaid={paid} />}
      {order?.items?.length > 0 && !order.pending?.length && !order.paid?.length && <button className="text-button cancel-link" disabled={busy} data-testid="table-cancel-button" onClick={cancel}><Trash2 size={12} /> Hesabı iptal et</button>}
      <ProductPicker products={products} onPick={add} />
    </div>
  );
}

export const TablesBoard = ({ onAddTable, onEditTable, onDeleteTable, onChanged, refreshKey }) => {
  const [data, setData] = useState({ tables: [], products: [] });
  const [openId, setOpenId] = useState(null);
  const load = useCallback(() => axios.get(`${API}/tables-view`).then(({ data: d }) => setData(d)).catch((e) => toast.error(errorText(e, "Masalar yüklenemedi"))), []);
  useEffect(() => { load(); }, [load, refreshKey]);
  useEffect(() => { const id = setInterval(load, 15000); return () => clearInterval(id); }, [load]);
  const open = data.tables.find((t) => t.id === openId);
  const busy = data.tables.filter((t) => t.order).length;
  return (
    <div className="tables-board" data-testid="tables-board">
      <div className="tables-head"><span className="muted" data-testid="tables-open-count">{busy} / {data.tables.length} masa dolu · açık hesap toplamı {money(data.tables.reduce((s, t) => s + (t.order?.total || 0), 0))}</span>{onAddTable && <button className="primary-button" data-testid="add-table-button" onClick={onAddTable}><Plus size={16} /> Masa ekle</button>}</div>
      {!data.tables.length && <div className="empty-state">{onAddTable ? "Henüz masa yok. Masa ekleyerek başlayın." : "Henüz masa tanımlanmadı. Yöneticinizden masa eklemesini isteyin."}</div>}
      <div className={`tables-layout ${open ? "with-order" : ""}`}>
        <div className="tables-grid">
          {data.tables.map((t) => (
            <div key={t.id} role="button" tabIndex={0} className={`table-tile ${t.order ? "busy" : ""} ${openId === t.id ? "selected" : ""}`} data-testid={`table-tile-${t.name}`} onClick={() => setOpenId(t.id)}>
              <div className="table-tile-top"><Armchair size={16} /><span>{t.seats} kişilik</span>{onEditTable && <span className="table-tile-actions"><button className="text-button tiny" data-testid={`table-edit-${t.name}`} onClick={(e) => { e.stopPropagation(); onEditTable(t); }}>Düzenle</button><button className="text-button tiny danger-inline" data-testid={`table-delete-${t.name}`} onClick={(e) => { e.stopPropagation(); if (window.confirm(`Masa ${t.name} silinsin mi?`)) onDeleteTable(t.id); }}>Sil</button></span>}</div>
              <b className={t.name.length > 6 ? "long" : ""}>{t.name}</b>
              <small>{t.order ? `${money(t.order.total)} · ${since(t.order.opened_at)}` : "Boş"}</small>
              {t.ready_count > 0 && <span className="ready-badge" data-testid={`table-ready-${t.name}`}><ChefHat size={11} /> Hazır</span>}
            </div>
          ))}
        </div>
        {open && <OrderPanel table={open} products={data.products} onChange={load} onDone={onChanged} onClose={() => setOpenId(null)} />}
      </div>
    </div>
  );
};

export const TablesView = (props) => (
  <>
    <div className="welcome-row"><div><p className="eyebrow">SALON</p><h2>Masalar</h2><p className="muted">Masaya ürün ekleyin, hesabı ödeme türüyle kapatın. Kapanan hesaplar satışa ve stoka, bahşişler bahşiş dağıtımına otomatik yazılır.</p></div></div>
    <TablesBoard {...props} />
  </>
);
