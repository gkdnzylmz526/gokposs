import { useEffect, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Copy, MessageCircle, ShoppingCart } from "lucide-react";
import { waPhone } from "@/lib/phone";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const num = (n) => Number(Number(n || 0).toFixed(3)).toLocaleString("tr-TR");
const money = (n) => new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY", maximumFractionDigits: 2 }).format(n || 0);

const orderText = (group) => [
  `Merhaba${group.supplier !== "Tedarikçi belirtilmemiş" ? ` ${group.supplier}` : ""},`,
  "GÖKPOS sipariş listemiz:",
  ...group.items.map((i) => `- ${i.name}: ${num(i.suggested)} ${i.unit}`),
  "Teşekkürler.",
].join("\n");

const saveOrder = (group, channel) => axios.post(`${API}/orders`, { supplier: group.supplier, phone: group.phone || "", channel, estimated_total: group.estimated_total, items: group.items.map((i) => ({ inventory_id: i.inventory_id, name: i.name, unit: i.unit, quantity: i.suggested, unit_price: i.unit_price || 0 })) }).then(() => toast.success("Sipariş geçmişe kaydedildi")).catch(() => toast.error("Sipariş geçmişe kaydedilemedi"));
const copy = async (text, group) => { try { await navigator.clipboard.writeText(text); toast.success("Sipariş listesi kopyalandı"); saveOrder(group, "Kopyalandı"); } catch { toast.error("Kopyalanamadı"); } };

export const OrderList = ({ refreshKey }) => {
  const [groups, setGroups] = useState([]);
  useEffect(() => { axios.get(`${API}/order-list`).then(({ data }) => setGroups(data)).catch(() => setGroups([])); }, [refreshKey]);
  const total = groups.reduce((sum, g) => sum + g.estimated_total, 0);
  return (
    <section className="panel order-panel" data-testid="order-list">
      <div className="panel-head">
        <div><h3>Otomatik sipariş listesi</h3><span className="muted">Kritik seviyedeki malzemeler, alış geçmişine göre en ucuz tedarikçiye gruplanır · önerilen miktar = hedef seviye − mevcut (hedef yoksa minimumun 2 katı)</span></div>
        <ShoppingCart size={20} className="panel-icon" />
      </div>
      {!groups.length && <div className="empty-state">Sipariş gereken malzeme yok. Tüm stoklar minimumun üzerinde.</div>}
      <div className="order-groups">
        {groups.map((g, gi) => (
          <article className="order-group" key={g.supplier} data-testid={`order-group-${gi}`}>
            <div className="order-group-head"><b>{g.supplier}{g.phone && <small data-testid={`order-phone-${gi}`}>{g.phone}</small>}</b><span>{money(g.estimated_total)}</span></div>
            {g.items.map((i, ii) => (
              <div className="order-item" key={i.inventory_id} data-testid={`order-item-${gi}-${ii}`}>
                <span>{i.name}<small>Mevcut {num(i.quantity)} / min {num(i.minimum)} {i.unit}{i.unit_price ? ` · ${money(i.unit_price)}/${i.unit}` : ""}</small>{i.cheapest && <small className="cheapest-note" data-testid={`order-cheapest-${gi}-${ii}`}>En ucuz tedarikçi{i.assigned_supplier && i.assigned_supplier !== g.supplier ? ` · kayıtlı: ${i.assigned_supplier}` : ""}{i.saving > 0 ? ` · ${money(i.saving)} tasarruf` : ""}</small>}</span>
                <strong>{num(i.suggested)} {i.unit}{i.estimated_cost > 0 && <small>{money(i.estimated_cost)}</small>}</strong>
              </div>
            ))}
            <div className="order-actions">
              <button className="secondary-button" data-testid={`order-copy-${gi}`} onClick={() => copy(orderText(g), g)}><Copy size={14} /> Kopyala</button>
              <a className="secondary-button" data-testid={`order-whatsapp-${gi}`} href={`https://wa.me/${waPhone(g.phone)}?text=${encodeURIComponent(orderText(g))}`} target="_blank" rel="noreferrer" onClick={() => saveOrder(g, "WhatsApp")}><MessageCircle size={14} /> {g.phone ? "WhatsApp'ta gönder" : "WhatsApp"}</a>
            </div>
          </article>
        ))}
      </div>
      {groups.length > 0 && <div className="order-total" data-testid="order-total"><span>Tahmini toplam maliyet</span><b>{money(total)}</b></div>}
    </section>
  );
};
