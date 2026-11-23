import { useEffect, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Copy, MessageCircle, ShoppingCart } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const num = (n) => Number(Number(n || 0).toFixed(3)).toLocaleString("tr-TR");
const money = (n) => new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY", maximumFractionDigits: 2 }).format(n || 0);

const orderText = (group) => [
  `Merhaba${group.supplier !== "Tedarikçi belirtilmemiş" ? ` ${group.supplier}` : ""},`,
  "GÖKBOSS POS sipariş listemiz:",
  ...group.items.map((i) => `- ${i.name}: ${num(i.suggested)} ${i.unit}`),
  "Teşekkürler.",
].join("\n");

const copy = async (text) => { try { await navigator.clipboard.writeText(text); toast.success("Sipariş listesi kopyalandı"); } catch { toast.error("Kopyalanamadı"); } };

export const OrderList = ({ refreshKey }) => {
  const [groups, setGroups] = useState([]);
  useEffect(() => { axios.get(`${API}/order-list`).then(({ data }) => setGroups(data)).catch(() => setGroups([])); }, [refreshKey]);
  const total = groups.reduce((sum, g) => sum + g.estimated_total, 0);
  return (
    <section className="panel order-panel" data-testid="order-list">
      <div className="panel-head">
        <div><h3>Otomatik sipariş listesi</h3><span className="muted">Kritik seviyedeki malzemeler · önerilen miktar = hedef seviye − mevcut (hedef yoksa minimumun 2 katı)</span></div>
        <ShoppingCart size={20} className="panel-icon" />
      </div>
      {!groups.length && <div className="empty-state">Sipariş gereken malzeme yok. Tüm stoklar minimumun üzerinde.</div>}
      <div className="order-groups">
        {groups.map((g, gi) => (
          <article className="order-group" key={g.supplier} data-testid={`order-group-${gi}`}>
            <div className="order-group-head"><b>{g.supplier}</b><span>{money(g.estimated_total)}</span></div>
            {g.items.map((i, ii) => (
              <div className="order-item" key={i.inventory_id} data-testid={`order-item-${gi}-${ii}`}>
                <span>{i.name}<small>Mevcut {num(i.quantity)} / min {num(i.minimum)} {i.unit}</small></span>
                <strong>{num(i.suggested)} {i.unit}</strong>
              </div>
            ))}
            <div className="order-actions">
              <button className="secondary-button" data-testid={`order-copy-${gi}`} onClick={() => copy(orderText(g))}><Copy size={14} /> Kopyala</button>
              <a className="secondary-button" data-testid={`order-whatsapp-${gi}`} href={`https://wa.me/?text=${encodeURIComponent(orderText(g))}`} target="_blank" rel="noreferrer"><MessageCircle size={14} /> WhatsApp</a>
            </div>
          </article>
        ))}
      </div>
      {groups.length > 0 && <div className="order-total" data-testid="order-total"><span>Tahmini toplam maliyet</span><b>{money(total)}</b></div>}
    </section>
  );
};
