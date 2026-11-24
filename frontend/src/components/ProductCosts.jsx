import { Fragment, useEffect, useMemo, useState } from "react";
import axios from "axios";
import { Calculator, ChevronDown, ChevronRight, Plus, Printer, Trash2 } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const money = (n) => new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY", maximumFractionDigits: 2 }).format(n || 0);
const pct = (n) => (n == null ? "—" : `%${Number(n).toLocaleString("tr-TR")}`);

const esc = (v) => String(v ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const card = (p, restaurants) => `<section class="card"><header><div><small>${esc(p.category)}</small><h2>${esc(p.name)}</h2></div><div class="price">${money(p.price)}<small>satış fiyatı</small></div></header>
<table><thead><tr><th>Malzeme</th><th>Miktar</th><th>Birim fiyat</th><th>Tutar</th></tr></thead><tbody>${p.lines.map((l) => `<tr><td>${esc(l.name)}</td><td>${l.amount.toLocaleString("tr-TR")} ${esc(l.unit)}</td><td>${money(l.unit_price)}</td><td>${money(l.cost)}</td></tr>`).join("") || `<tr><td colspan="4">Tarif girilmemiş</td></tr>`}</tbody>
<tfoot><tr><td colspan="3">Porsiyon maliyeti (ortalama)</td><td>${money(p.cost)}</td></tr></tfoot></table>
<div class="stats"><div><small>Kâr</small><b>${money(p.profit)}</b></div><div><small>Kâr marjı</small><b>${pct(p.margin)}</b></div><div><small>Gıda maliyeti</small><b>${pct(p.food_cost_pct)}</b></div><div><small>Önerilen fiyat (%${p.target_margin})</small><b>${p.suggested_price ? money(p.suggested_price) : "—"}</b></div></div>
<div class="rest">${restaurants.map((r) => `<span>${esc(r.name)}: <b>${p.has_recipe ? money(p.per_restaurant[r.id].cost) : "—"}</b>${p.per_restaurant[r.id].missing.length ? " (eksik fiyat)" : ""}</span>`).join("")}</div></section>`;
const printCards = (products, restaurants) => {
  const w = window.open("", "_blank");
  if (!w) return;
  w.document.write(`<!doctype html><html lang="tr"><head><meta charset="utf-8"><title>GÖKBOSS POS · Maliyet kartları</title><style>
body{font-family:Arial,Helvetica,sans-serif;color:#1e293b;margin:24px}h1{font-size:14px;letter-spacing:2px;color:#b45309;margin:0 0 4px}.meta{font-size:11px;color:#64748b;margin-bottom:18px}
.card{border:1px solid #cbd5e1;border-radius:8px;padding:16px 18px;margin-bottom:16px;page-break-inside:avoid}header{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:2px solid #1e293b;padding-bottom:8px;margin-bottom:10px}
header small{font-size:10px;text-transform:uppercase;color:#64748b;letter-spacing:1px}h2{margin:2px 0 0;font-size:20px}.price{font-size:20px;font-weight:bold;text-align:right}.price small{display:block;font-size:10px;font-weight:normal;color:#64748b}
table{width:100%;border-collapse:collapse;font-size:12px}th{text-align:left;font-size:10px;text-transform:uppercase;color:#64748b;border-bottom:1px solid #e2e8f0;padding:5px 4px}td{padding:5px 4px;border-bottom:1px dashed #e2e8f0}td:last-child,th:last-child{text-align:right}
tfoot td{font-weight:bold;border-bottom:none;border-top:1px solid #1e293b}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:10px}.stats div{background:#f8fafc;border-radius:6px;padding:7px 9px}.stats small{display:block;font-size:9px;color:#64748b}.stats b{font-size:14px}
.rest{display:flex;gap:14px;flex-wrap:wrap;margin-top:8px;font-size:10px;color:#475569}@media print{body{margin:10mm}}</style></head><body><h1>GÖKBOSS POS · MALİYET KARTI</h1><div class="meta">${new Date().toLocaleString("tr-TR")} · Maliyetler güncel alış fiyatlarıyla hesaplanmıştır</div>${products.map((p) => card(p, restaurants)).join("")}<script>window.onload=()=>setTimeout(()=>window.print(),200)</script></body></html>`);
  w.document.close();
};

function CostSummary({ data }) {
  const s = data.summary;
  const worst = [...data.products].filter((p) => p.has_recipe && p.price).sort((a, b) => a.margin - b.margin)[0];
  const cards = [["Tarifi olan ürün", `${s.with_recipe} / ${s.products}`, "cost-tile"], ["Ortalama gıda maliyeti", pct(s.avg_food_cost_pct), "cost-tile amber"], ["Hedef marjın altında", `${s.below_target} ürün`, s.below_target ? "cost-tile red" : "cost-tile green"], ["En düşük marj", worst ? `${worst.name} · ${pct(worst.margin)}` : "—", "cost-tile"]];
  return <div className="cost-summary">{cards.map(([label, value, cls], i) => <div key={label} className={cls} data-testid={`cost-summary-${i}`}><span>{label}</span><strong>{value}</strong></div>)}</div>;
}

function CostRow({ p, restaurants, open, onToggle, onEdit, onWizard }) {
  const below = p.has_recipe && p.margin < p.target_margin;
  return (
    <Fragment>
      <div className={`table-row cost-grid ${open ? "open" : ""}`} data-testid={`cost-row-${p.id}`} onClick={onToggle} role="button" tabIndex={0}>
        <span className="cost-name">{p.lines.length ? (open ? <ChevronDown size={14} /> : <ChevronRight size={14} />) : <i className="cost-spacer" />}<span><b>{p.name}</b><small className="muted block">{p.category}</small></span></span>
        <span className="table-amount">{money(p.price)}</span>
        <span className="table-amount" data-testid={`cost-avg-${p.id}`}>{p.has_recipe ? money(p.cost) : <button className="text-button tiny" data-testid={`cost-add-recipe-${p.id}`} onClick={(e) => { e.stopPropagation(); onWizard(p.id); }}>+ Sorularla tarif ekle</button>}</span>
        {restaurants.map((r) => { const c = p.per_restaurant[r.id]; return <span key={r.id} data-testid={`cost-${r.id}-${p.id}`} title={c.missing.length ? `Fiyatı eksik: ${c.missing.join(", ")}` : ""}>{p.has_recipe ? <>{money(c.cost)}{c.missing.length > 0 && <em className="missing-badge">eksik</em>}</> : "—"}</span>; })}
        <span className={below ? "danger-inline" : "green-text"} data-testid={`cost-margin-${p.id}`}>{p.has_recipe ? pct(p.margin) : "—"}</span>
        <span>{p.suggested_price ? money(p.suggested_price) : "—"}<small className="muted block">%{p.target_margin} hedef</small></span>
      </div>
      {open && p.lines.length > 0 && (
        <div className="cost-lines" data-testid={`cost-lines-${p.id}`}>
          <div className="cost-line head"><span>Malzeme</span><span>Miktar</span><span>Ort. birim fiyat</span><span>Tutar</span>{restaurants.map((r) => <span key={r.id}>{r.name}</span>)}</div>
          {p.lines.map((l) => <div key={l.name} className="cost-line"><span>{l.name}</span><span>{l.amount.toLocaleString("tr-TR")} {l.unit}</span><span>{money(l.unit_price)}</span><span><b>{money(l.cost)}</b></span>{restaurants.map((r) => <span key={r.id} className={l.per_restaurant[r.id] == null ? "muted" : ""}>{l.per_restaurant[r.id] == null ? "stokta yok" : money(l.per_restaurant[r.id])}</span>)}</div>)}
          <div className="report-actions"><button className="text-button" data-testid={`cost-edit-recipe-${p.id}`} onClick={() => onEdit(p.id)}>Tarifi düzenle</button><button className="text-button" data-testid={`cost-print-${p.id}`} onClick={() => printCards([p], restaurants)}><Printer size={12} /> Maliyet kartını yazdır</button></div>
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

export const ProductCostView = ({ refreshKey, inventory, onEditProduct, onCreateProduct, onRecipeWizard }) => {
  const [data, setData] = useState(null);
  const [open, setOpen] = useState({});
  useEffect(() => { axios.get(`${API}/product-costs`).then(({ data: d }) => setData(d)).catch(() => setData(null)); }, [refreshKey]);
  const cols = { "--rest-cols": data?.restaurants.length || 3 };
  return (
    <>
      <div className="welcome-row"><div><p className="eyebrow">KÂRLILIK</p><h2>Ürün Maliyeti</h2><p className="muted">Her menü ürününün maliyeti tarifindeki malzemelerin alış fiyatlarından otomatik hesaplanır. Alış fiyatı değiştikçe maliyetler kendiliğinden güncellenir.</p></div></div>
      {data && <CostSummary data={data} />}
      {data && <div className="cost-toolbar">{data.products.some((p) => !p.has_recipe) && <span className="muted" data-testid="cost-missing-recipes">Tarifi olmayan {data.products.filter((p) => !p.has_recipe).length} ürün var · satırdaki "Sorularla tarif ekle" ile tamamlayın</span>}<button className="secondary-button" data-testid="cost-print-all" onClick={() => printCards(data.products, data.restaurants)}><Printer size={14} /> Tüm maliyet kartlarını yazdır</button></div>}
      <section className="panel table-panel cost-table" data-testid="cost-table" style={cols}>
        <div className="spending-scroll">
          <div className="table-head cost-grid"><span>Ürün</span><span>Satış fiyatı</span><span>Ort. maliyet</span>{data?.restaurants.map((r) => <span key={r.id}>{r.name}</span>)}<span>Marj</span><span>Önerilen fiyat</span></div>
          {!data?.products.length && <div className="empty-state">Henüz menü ürünü yok.</div>}
          {data?.products.map((p) => <CostRow key={p.id} p={p} restaurants={data.restaurants} open={open[p.id]} onToggle={() => setOpen({ ...open, [p.id]: !open[p.id] })} onEdit={onEditProduct} onWizard={onRecipeWizard} />)}
        </div>
      </section>
      <CostCalculator inventory={inventory} onCreate={onCreateProduct} />
    </>
  );
};
