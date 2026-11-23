import { Fragment, useEffect, useMemo, useState } from "react";
import axios from "axios";
import { Calculator, ChevronDown, ChevronRight, Plus, Trash2 } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const money = (n) => new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY", maximumFractionDigits: 2 }).format(n || 0);
const pct = (n) => (n == null ? "—" : `%${Number(n).toLocaleString("tr-TR")}`);

function CostSummary({ data }) {
  const s = data.summary;
  const worst = [...data.products].filter((p) => p.has_recipe && p.price).sort((a, b) => a.margin - b.margin)[0];
  const cards = [["Tarifi olan ürün", `${s.with_recipe} / ${s.products}`, "cost-tile"], ["Ortalama gıda maliyeti", pct(s.avg_food_cost_pct), "cost-tile amber"], ["Hedef marjın altında", `${s.below_target} ürün`, s.below_target ? "cost-tile red" : "cost-tile green"], ["En düşük marj", worst ? `${worst.name} · ${pct(worst.margin)}` : "—", "cost-tile"]];
  return <div className="cost-summary">{cards.map(([label, value, cls], i) => <div key={label} className={cls} data-testid={`cost-summary-${i}`}><span>{label}</span><strong>{value}</strong></div>)}</div>;
}

function CostRow({ p, restaurants, open, onToggle, onEdit }) {
  const below = p.has_recipe && p.margin < p.target_margin;
  return (
    <Fragment>
      <div className={`table-row cost-grid ${open ? "open" : ""}`} data-testid={`cost-row-${p.id}`} onClick={onToggle} role="button" tabIndex={0}>
        <span className="cost-name">{p.lines.length ? (open ? <ChevronDown size={14} /> : <ChevronRight size={14} />) : <i className="cost-spacer" />}<span><b>{p.name}</b><small className="muted block">{p.category}</small></span></span>
        <span className="table-amount">{money(p.price)}</span>
        <span className="table-amount" data-testid={`cost-avg-${p.id}`}>{p.has_recipe ? money(p.cost) : <button className="text-button tiny" data-testid={`cost-add-recipe-${p.id}`} onClick={(e) => { e.stopPropagation(); onEdit(p.id); }}>+ Tarif ekle</button>}</span>
        {restaurants.map((r) => { const c = p.per_restaurant[r.id]; return <span key={r.id} data-testid={`cost-${r.id}-${p.id}`} title={c.missing.length ? `Fiyatı eksik: ${c.missing.join(", ")}` : ""}>{p.has_recipe ? <>{money(c.cost)}{c.missing.length > 0 && <em className="missing-badge">eksik</em>}</> : "—"}</span>; })}
        <span className={below ? "danger-inline" : "green-text"} data-testid={`cost-margin-${p.id}`}>{p.has_recipe ? pct(p.margin) : "—"}</span>
        <span>{p.suggested_price ? money(p.suggested_price) : "—"}<small className="muted block">%{p.target_margin} hedef</small></span>
      </div>
      {open && p.lines.length > 0 && (
        <div className="cost-lines" data-testid={`cost-lines-${p.id}`}>
          <div className="cost-line head"><span>Malzeme</span><span>Miktar</span><span>Ort. birim fiyat</span><span>Tutar</span>{restaurants.map((r) => <span key={r.id}>{r.name}</span>)}</div>
          {p.lines.map((l) => <div key={l.name} className="cost-line"><span>{l.name}</span><span>{l.amount.toLocaleString("tr-TR")} {l.unit}</span><span>{money(l.unit_price)}</span><span><b>{money(l.cost)}</b></span>{restaurants.map((r) => <span key={r.id} className={l.per_restaurant[r.id] == null ? "muted" : ""}>{l.per_restaurant[r.id] == null ? "stokta yok" : money(l.per_restaurant[r.id])}</span>)}</div>)}
          <button className="text-button" data-testid={`cost-edit-recipe-${p.id}`} onClick={() => onEdit(p.id)}>Tarifi düzenle</button>
        </div>
      )}
    </Fragment>
  );
}

function CostCalculator({ inventory, onCreate }) {
  const [rows, setRows] = useState([{ inventory_id: "", amount: "" }]);
  const [margin, setMargin] = useState(65);
  const [price, setPrice] = useState("");
  const avg = useMemo(() => { const by = {}; inventory.forEach((i) => { const k = i.name.toLocaleLowerCase("tr-TR").trim(); if (i.unit_cost > 0) (by[k] = by[k] || []).push(i.unit_cost); }); return (item) => { const v = by[item.name.toLocaleLowerCase("tr-TR").trim()] || []; return v.length ? v.reduce((a, b) => a + b, 0) / v.length : 0; }; }, [inventory]);
  const lines = rows.map((r) => { const item = inventory.find((i) => i.id === r.inventory_id); return { ...r, item, cost: item ? Number(r.amount || 0) * avg(item) : 0 }; });
  const total = lines.reduce((s, l) => s + l.cost, 0);
  const suggested = total > 0 && margin < 100 ? Math.ceil(total / (1 - margin / 100)) : 0;
  const realMargin = Number(price) > 0 ? ((Number(price) - total) / Number(price)) * 100 : null;
  const update = (i, patch) => setRows(rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  return (
    <section className="panel cost-calculator" data-testid="cost-calculator">
      <div className="panel-head"><div><h3><Calculator size={17} /> Maliyet hesaplayıcı</h3><span className="muted">Yeni bir ürünü menüye eklemeden önce malzemelerini girin, maliyetini ve önerilen fiyatını görün (3 restoranın ortalama alış fiyatı)</span></div></div>
      <div className="calc-rows">
        {lines.map((l, i) => (
          <div key={i} className="calc-row" data-testid={`calc-row-${i}`}>
            <select value={l.inventory_id} data-testid={`calc-ingredient-${i}`} onChange={(e) => update(i, { inventory_id: e.target.value })}><option value="">Malzeme seçin</option>{inventory.map((it) => <option key={it.id} value={it.id}>{it.name} ({it.unit})</option>)}</select>
            <input type="number" step="any" min="0" placeholder="Miktar" value={l.amount} data-testid={`calc-amount-${i}`} onChange={(e) => update(i, { amount: e.target.value })} />
            <span className="calc-line-cost">{l.item ? `${money(avg(l.item))}/${l.item.unit}` : ""}<b>{money(l.cost)}</b></span>
            <button className="icon-button" data-testid={`calc-remove-${i}`} onClick={() => setRows(rows.filter((_, idx) => idx !== i))}><Trash2 size={14} /></button>
          </div>
        ))}
        <button className="text-button" data-testid="calc-add-row" onClick={() => setRows([...rows, { inventory_id: "", amount: "" }])}><Plus size={12} /> Malzeme ekle</button>
      </div>
      <div className="calc-result">
        <label>Hedef kâr marjı (%)<input type="number" min="0" max="99" value={margin} data-testid="calc-margin" onChange={(e) => setMargin(Number(e.target.value))} /></label>
        <label>Düşündüğünüz satış fiyatı (₺)<input type="number" min="0" value={price} placeholder="isteğe bağlı" data-testid="calc-price" onChange={(e) => setPrice(e.target.value)} /></label>
        <div><span>Toplam maliyet</span><strong data-testid="calc-total">{money(total)}</strong></div>
        <div><span>Önerilen fiyat</span><strong className="amber-text" data-testid="calc-suggested">{money(suggested)}</strong></div>
        {realMargin != null && <div><span>Bu fiyatla marj</span><strong className={realMargin < margin ? "danger-inline" : "green-text"} data-testid="calc-real-margin">%{realMargin.toFixed(1).replace(".", ",")}</strong></div>}
      </div>
      <button className="primary-button" disabled={!total} data-testid="calc-create-product" onClick={() => onCreate({ recipe: lines.filter((l) => l.item && Number(l.amount) > 0).map((l) => ({ inventory_id: l.inventory_id, amount: l.amount })), price: Number(price) || suggested, target_margin: margin })}><Plus size={15} /> Bu tarifle menüye ürün ekle</button>
    </section>
  );
}

export const ProductCostView = ({ refreshKey, inventory, onEditProduct, onCreateProduct }) => {
  const [data, setData] = useState(null);
  const [open, setOpen] = useState({});
  useEffect(() => { axios.get(`${API}/product-costs`).then(({ data: d }) => setData(d)).catch(() => setData(null)); }, [refreshKey]);
  const cols = { "--rest-cols": data?.restaurants.length || 3 };
  return (
    <>
      <div className="welcome-row"><div><p className="eyebrow">KÂRLILIK</p><h2>Ürün Maliyeti</h2><p className="muted">Her menü ürününün maliyeti tarifindeki malzemelerin alış fiyatlarından otomatik hesaplanır. Alış fiyatı değiştikçe maliyetler kendiliğinden güncellenir.</p></div></div>
      {data && <CostSummary data={data} />}
      <section className="panel table-panel cost-table" data-testid="cost-table" style={cols}>
        <div className="spending-scroll">
          <div className="table-head cost-grid"><span>Ürün</span><span>Satış fiyatı</span><span>Ort. maliyet</span>{data?.restaurants.map((r) => <span key={r.id}>{r.name}</span>)}<span>Marj</span><span>Önerilen fiyat</span></div>
          {!data?.products.length && <div className="empty-state">Henüz menü ürünü yok.</div>}
          {data?.products.map((p) => <CostRow key={p.id} p={p} restaurants={data.restaurants} open={open[p.id]} onToggle={() => setOpen({ ...open, [p.id]: !open[p.id] })} onEdit={onEditProduct} />)}
        </div>
      </section>
      <CostCalculator inventory={inventory} onCreate={onCreateProduct} />
    </>
  );
};
