import { useEffect, useState } from "react";
import axios from "axios";
import { History } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const num = (n) => Number(Number(n || 0).toFixed(3)).toLocaleString("tr-TR");

export const StockMovements = ({ inventory, refreshKey }) => {
  const [rows, setRows] = useState([]);
  const [filter, setFilter] = useState("");
  useEffect(() => {
    axios.get(`${API}/stock-movements`, { params: filter ? { inventory_id: filter } : {} }).then(({ data }) => setRows(data)).catch(() => setRows([]));
  }, [filter, refreshKey]);
  return (
    <section className="panel table-panel movements-panel" data-testid="stock-movements">
      <div className="panel-head movements-head">
        <div><h3>Stok hareketleri</h3><span className="muted">Hangi satış hangi malzemeyi ne kadar düşürdü</span></div>
        <div className="movements-filter">
          <History size={18} className="panel-icon" />
          <select value={filter} onChange={(e) => setFilter(e.target.value)} data-testid="stock-movements-filter">
            <option value="">Tüm malzemeler</option>
            {inventory.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
          </select>
        </div>
      </div>
      <div className="table-head movements-grid"><span>Tarih</span><span>Malzeme</span><span>Değişim</span><span>Kalan</span><span>Neden</span></div>
      {!rows.length && <div className="empty-state">Henüz stok hareketi yok.</div>}
      {rows.map((m, i) => (
        <div className="table-row movements-grid" key={m.id} data-testid={`stock-movement-row-${i}`}>
          <span>{new Date(m.created_at).toLocaleString("tr-TR", { dateStyle: "short", timeStyle: "short" })}</span>
          <span>{m.inventory_name}</span>
          <span className={`table-amount movement-delta ${m.delta < 0 ? "neg" : "pos"}`}>{m.delta > 0 ? "+" : ""}{num(m.delta)} {m.unit}</span>
          <span>{num(m.quantity_after)} {m.unit}</span>
          <span>{m.reason}{m.product_name ? ` · ${m.product_name} × ${num(m.sale_quantity)}` : ""}</span>
        </div>
      ))}
    </section>
  );
};
