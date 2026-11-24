import { useState } from "react";
import { Check, X } from "lucide-react";

const money = (n) => new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY", maximumFractionDigits: 2 }).format(n || 0);

export const suggestedPrice = (product, ratio = 0) => { const margin = Number(product.target_margin) || 65; const room = 1 - margin / 100 - ratio / 100; return product.cost > 0 && room > 0.01 ? Math.ceil(Number((product.cost / room).toFixed(6))) : null; };

export const BulkPriceDialog = ({ products, ratio = 0, onClose, onApply }) => {
  const changes = products.map((p) => ({ ...p, suggested: suggestedPrice(p, ratio) })).filter((p) => p.suggested && p.suggested !== p.price);
  const [selected, setSelected] = useState(() => new Set(changes.map((p) => p.id)));
  const toggle = (id) => setSelected((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  return (
    <div className="modal-backdrop">
      <div className="modal bulk-modal" data-testid="bulk-price-dialog">
        <button className="icon-button close" data-testid="bulk-price-close" onClick={onClose}><X size={18} /></button>
        <span className="eyebrow">TOPLU FİYAT GÜNCELLEME</span>
        <h2>Önerilen fiyatları uygula</h2>
        {!changes.length ? <div className="empty-state">Tüm ürünler zaten önerilen fiyatta ya da maliyeti girilmemiş.</div> : (
          <div className="bulk-list">
            {changes.map((p) => (
              <label key={p.id} className="bulk-row" data-testid={`bulk-price-row-${p.id}`}>
                <input type="checkbox" checked={selected.has(p.id)} onChange={() => toggle(p.id)} data-testid={`bulk-price-check-${p.id}`} />
                <span><b>{p.name}</b><small>maliyet {money(p.cost)} · hedef %{Number(p.target_margin) || 65}</small></span>
                <span className="bulk-prices">{money(p.price)} → <b className={p.suggested > p.price ? "up" : "down"}>{money(p.suggested)}</b></span>
              </label>
            ))}
          </div>
        )}
        <button className="primary-button full" data-testid="bulk-price-confirm" disabled={!selected.size} onClick={() => onApply([...selected])}><Check size={17} /> {selected.size} ürünün fiyatını güncelle</button>
      </div>
    </div>
  );
};
