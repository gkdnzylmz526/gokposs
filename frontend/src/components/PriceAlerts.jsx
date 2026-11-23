import { useEffect, useState } from "react";
import axios from "axios";
import { TrendingUp, X } from "lucide-react";
import { toast } from "sonner";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const money = (n) => new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY", maximumFractionDigits: 2 }).format(n || 0);
const pct = (n) => `%${Number(n || 0).toLocaleString("tr-TR")}`;

export const PriceAlerts = ({ refreshKey }) => {
  const [alerts, setAlerts] = useState([]);
  const load = () => axios.get(`${API}/price-alerts`).then(({ data }) => setAlerts(data)).catch(() => setAlerts([]));
  useEffect(() => { load(); }, [refreshKey]);
  const dismiss = async (id) => { try { await axios.post(`${API}/price-alerts/${id}/dismiss`); setAlerts((a) => a.filter((x) => x.id !== id)); } catch { toast.error("Uyarı kapatılamadı"); } };
  if (!alerts.length) return null;
  return (
    <section className="price-alerts" data-testid="price-alerts">
      {alerts.map((a, i) => (
        <article className="price-alert" key={a.id} data-testid={`price-alert-${i}`}>
          <div className="price-alert-icon"><TrendingUp size={18} /></div>
          <div className="price-alert-body">
            <b>{a.inventory_name} alış fiyatı {pct(a.change_pct)} arttı</b>
            <small>{money(a.old_price)} → {money(a.new_price)} / {a.unit} · {new Date(a.created_at).toLocaleDateString("tr-TR")}</small>
            {a.affected.length ? (
              <ul>{a.affected.map((p) => <li key={p.product_id} data-testid={`price-alert-${i}-product-${p.product_id}`}><span>{p.name}</span><span>maliyet {money(p.old_cost)} → {money(p.new_cost)}</span><span className="danger-inline">marj {pct(p.old_margin)} → {pct(p.new_margin)}</span></li>)}</ul>
            ) : <small>Bu malzemeyi kullanan tarifli ürün yok.</small>}
          </div>
          <button className="icon-button" title="Kapat" data-testid={`price-alert-dismiss-${i}`} onClick={() => dismiss(a.id)}><X size={14} /></button>
        </article>
      ))}
    </section>
  );
};
