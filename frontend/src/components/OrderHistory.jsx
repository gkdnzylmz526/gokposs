import { useEffect, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { PackageCheck, Trash2 } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const money = (n) => new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY", maximumFractionDigits: 2 }).format(n || 0);
const num = (n) => Number(Number(n || 0).toFixed(3)).toLocaleString("tr-TR");

export const OrderHistory = ({ suppliers, refreshKey }) => {
  const [orders, setOrders] = useState([]);
  const [filter, setFilter] = useState("");
  const load = () => axios.get(`${API}/orders`).then(({ data }) => setOrders(data)).catch(() => setOrders([]));
  useEffect(() => { load(); }, [refreshKey]);
  const toggle = async (o) => { const delivering = o.status !== "Teslim alındı"; if (!window.confirm(delivering ? "Sipariş teslim alındı olarak işaretlensin mi?\nKalemler stoka eklenecek, alış fiyatları güncellenecek ve bir gider kaydı oluşturulacak." : "Teslimat geri alınsın mı?\nEklenen stok çıkarılacak ve oluşturulan gider kaydı silinecek.")) return; try { await axios.put(`${API}/orders/${o.id}`, { ...o, status: o.status === "Teslim alındı" ? "Gönderildi" : "Teslim alındı" }); load(); toast.success(delivering ? "Teslim alındı · stok ve gider güncellendi" : "Teslimat geri alındı"); } catch { toast.error("Durum güncellenemedi"); } };
  const remove = async (o) => { if (!window.confirm("Bu sipariş kaydı silinsin mi?")) return; try { await axios.delete(`${API}/orders/${o.id}`); load(); } catch { toast.error("Silinemedi"); } };
  const names = [...new Set([...suppliers.map((s) => s.name), ...orders.map((o) => o.supplier)])];
  const shown = orders.filter((o) => !filter || o.supplier === filter);
  return (
    <section className="panel order-history" data-testid="order-history">
      <div className="panel-head">
        <div><h3>Sipariş geçmişi</h3><span className="muted">Sipariş listesinden kopyalanan veya WhatsApp'tan gönderilen siparişler</span></div>
        <div className="movements-filter"><PackageCheck size={18} className="panel-icon" />
          <select value={filter} onChange={(e) => setFilter(e.target.value)} data-testid="order-history-filter"><option value="">Tüm tedarikçiler</option>{names.map((n) => <option key={n} value={n}>{n}</option>)}</select>
        </div>
      </div>
      {!shown.length && <div className="empty-state">Henüz kayıtlı sipariş yok.</div>}
      <div className="history-list">
        {shown.map((o, i) => (
          <article key={o.id} className={`history-card ${o.status === "Teslim alındı" ? "done" : ""}`} data-testid={`order-history-row-${i}`}>
            <div className="history-head">
              <div><b>{o.supplier}</b><small>{new Date(o.created_at).toLocaleString("tr-TR", { dateStyle: "medium", timeStyle: "short" })} · {o.channel}</small></div>
              <strong>{money(o.estimated_total)}</strong>
            </div>
            <ul>{o.items.map((it, j) => <li key={j}><span>{it.name}</span><span>{num(it.quantity)} {it.unit}{it.unit_price ? ` · ${money(it.unit_price)}/${it.unit}` : ""}</span></li>)}</ul>
            <div className="history-actions">
              <button className={`status-pill ${o.status === "Teslim alındı" ? "done" : ""}`} data-testid={`order-history-status-${i}`} onClick={() => toggle(o)}>{o.status === "Teslim alındı" ? "✓ Teslim alındı" : "Gönderildi · teslim alındı işaretle"}</button>
              {o.expense_id && <small className="expense-note" data-testid={`order-history-expense-${i}`}>Gider kaydı oluşturuldu</small>}
              <button className="icon-button" title="Sil" data-testid={`order-history-delete-${i}`} onClick={() => remove(o)}><Trash2 size={14} /></button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
};
