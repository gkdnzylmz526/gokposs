import { useMemo, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { ArrowLeft, Sparkles, Trash2, X } from "lucide-react";
import { errorText } from "@/lib/restaurant";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const money = (n) => new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY", maximumFractionDigits: 2 }).format(n || 0);
const key = (n) => (n || "").toLocaleLowerCase("tr-TR").trim();
const UNITS = ["kg", "gr", "lt", "ml", "adet", "paket", "porsiyon"];
const SUB = { kg: ["gr", 1000], lt: ["ml", 1000] };
const num = (v) => Number(String(v).replace(",", "."));

function Question({ title, hint, children }) {
  return <div className="wiz-question"><h3 data-testid="wizard-question">{title}</h3>{hint && <p className="muted">{hint}</p>}{children}</div>;
}

function Recap({ lines, onRemove }) {
  const total = lines.reduce((s, l) => s + l.cost, 0);
  return (
    <aside className="wiz-recap" data-testid="wizard-recap">
      <span className="eyebrow">TARİF</span>
      {!lines.length && <p className="muted">Malzemeler burada birikecek.</p>}
      {lines.map((l, i) => <div key={i} className="wiz-line" data-testid={`wizard-line-${i}`}><span><b>{l.name}</b><small>{l.amount.toLocaleString("tr-TR")} {l.unit} × {money(l.unit_cost)}</small></span><strong>{money(l.cost)}</strong><button title="Çıkar" data-testid={`wizard-line-remove-${i}`} onClick={() => onRemove(i)}><Trash2 size={12} /></button></div>)}
      <div className="wiz-total"><span>Porsiyon maliyeti</span><strong data-testid="wizard-total-cost">{money(total)}</strong></div>
    </aside>
  );
}

export const ProductWizard = ({ inventory, categories, onClose, onSaved }) => {
  const known = useMemo(() => { const by = {}; inventory.forEach((i) => { const k = key(i.name); by[k] = by[k] || { name: i.name, unit: i.unit, prices: [] }; if (i.unit_cost > 0) by[k].prices.push(i.unit_cost); }); return Object.fromEntries(Object.entries(by).map(([k, v]) => [k, { ...v, unit_cost: v.prices.length ? v.prices.reduce((a, b) => a + b, 0) / v.prices.length : 0 }])); }, [inventory]);
  const [step, setStep] = useState("name");
  const [history, setHistory] = useState([]);
  const [product, setProduct] = useState({ name: "", category: categories[0] || "Genel" });
  const [draft, setDraft] = useState({ name: "", unit: "kg", unit_cost: "", amount: "", useSub: true });
  const [lines, setLines] = useState([]);
  const [margin, setMargin] = useState(65);
  const [price, setPrice] = useState("");
  const [saving, setSaving] = useState(false);
  const go = (next) => { setHistory([...history, step]); setStep(next); };
  const back = () => { setStep(history[history.length - 1]); setHistory(history.slice(0, -1)); };
  const cost = lines.reduce((s, l) => s + l.cost, 0);
  const suggested = cost > 0 ? Math.ceil(cost / (1 - margin / 100)) : 0;
  const match = known[key(draft.name)];
  const sub = SUB[draft.unit];

  const pickIngredient = () => {
    if (lines.some((l) => key(l.name) === key(draft.name))) return toast.error("Bu malzeme zaten tarifte");
    if (match) { setDraft({ ...draft, name: match.name, unit: match.unit, unit_cost: match.unit_cost || "", useSub: Boolean(SUB[match.unit]) }); return go(match.unit_cost > 0 ? "amount" : "price"); }
    go("price");
  };
  const addLine = () => {
    const stockAmount = sub && draft.useSub ? num(draft.amount) / sub[1] : num(draft.amount);
    const unitCost = num(draft.unit_cost || 0);
    setLines([...lines, { name: draft.name.trim(), unit: draft.unit, unit_cost: unitCost, amount: Math.round(stockAmount * 10000) / 10000, cost: stockAmount * unitCost, isNew: !match, priced: !match || !(match.unit_cost > 0) }]);
    setDraft({ name: "", unit: "kg", unit_cost: "", amount: "", useSub: true });
    setHistory([]); setStep("more");
  };
  const save = async () => {
    setSaving(true);
    try {
      const { data } = await axios.post(`${API}/products/wizard`, { name: product.name, category: product.category, price: num(price), target_margin: margin, ingredients: lines.map((l) => ({ name: l.name, unit: l.unit, amount: l.amount, ...(l.priced && { unit_cost: l.unit_cost }) })) });
      toast.success(`${data.product.name} menüye eklendi · maliyet ${money(data.product.cost)}${data.created_ingredients.length ? ` · ${data.created_ingredients.length} yeni stok kalemi açıldı` : ""}`);
      onSaved(); onClose();
    } catch (e) { toast.error(errorText(e, "Ürün kaydedilemedi")); } finally { setSaving(false); }
  };

  const enter = (fn, ok) => (e) => { if (e.key === "Enter" && ok) fn(); };
  const steps = {
    name: <Question title="Ürünün adı ne?" hint="Menüde görünecek ad. Örn. Kıymalı Pide">
      <input autoFocus value={product.name} data-testid="wizard-name-input" placeholder="Ürün adı" onChange={(e) => setProduct({ ...product, name: e.target.value })} onKeyDown={enter(() => go("category"), product.name.trim())} />
      <button className="primary-button" disabled={!product.name.trim()} data-testid="wizard-next" onClick={() => go("category")}>Devam</button>
    </Question>,
    category: <Question title={`${product.name} hangi kategoride?`}>
      <div className="wiz-chips">{[...categories, "Pide", "Dürüm", "Kebap", "İçecek", "Tatlı"].filter((c, i, all) => all.findIndex((x) => key(x) === key(c)) === i).map((c) => <button key={c} className={product.category === c ? "active" : ""} data-testid={`wizard-category-${c}`} onClick={() => setProduct({ ...product, category: c })}>{c}</button>)}</div>
      <input value={product.category} data-testid="wizard-category-input" placeholder="veya yeni kategori yazın" onChange={(e) => setProduct({ ...product, category: e.target.value })} />
      <button className="primary-button" disabled={!product.category.trim()} data-testid="wizard-next" onClick={() => go("ingredient")}>Devam</button>
    </Question>,
    ingredient: <Question title={lines.length ? "Sıradaki malzeme hangisi?" : `${product.name} içinde hangi malzemeler var? İlkini yazın.`} hint="Stokta olanlar listede çıkar. Yoksa yeni malzeme olarak eklenir.">
      <input autoFocus list="wizard-known" value={draft.name} data-testid="wizard-ingredient-input" placeholder="örn. Kıyma" onChange={(e) => setDraft({ ...draft, name: e.target.value })} onKeyDown={enter(pickIngredient, draft.name.trim())} />
      <datalist id="wizard-known">{Object.values(known).map((k) => <option key={k.name} value={k.name}>{`${k.unit}${k.unit_cost ? ` · ${money(k.unit_cost)}` : ""}`}</option>)}</datalist>
      {draft.name.trim() && <small className={match ? "green-text" : "amber-text"} data-testid="wizard-ingredient-status">{match ? `Stokta var · ${match.unit}${match.unit_cost ? ` · ortalama ${money(match.unit_cost)}/${match.unit}` : " · fiyatı girilmemiş"}` : "Yeni malzeme — birazdan birimini ve fiyatını soracağım"}</small>}
      <button className="primary-button" disabled={!draft.name.trim()} data-testid="wizard-next" onClick={pickIngredient}>Devam</button>
    </Question>,
    price: <Question title={match ? `${draft.name} fiyatı kaç TL?` : `${draft.name} nasıl alıyorsunuz?`} hint={match ? "Bu malzemenin alış fiyatı kayıtlı değil." : "Fiyat üç restoranın stoğuna da aynı yazılır; her restoran sonra kendi fiyatını güncelleyebilir."}>
      {!match && <div className="wiz-chips">{UNITS.map((u) => <button key={u} className={draft.unit === u ? "active" : ""} data-testid={`wizard-unit-${u}`} onClick={() => setDraft({ ...draft, unit: u })}>{u}</button>)}</div>}
      <label className="wiz-inline">1 {draft.unit} {draft.name} =<input autoFocus type="number" min="0" step="any" value={draft.unit_cost} data-testid="wizard-unit-cost-input" placeholder="0" onChange={(e) => setDraft({ ...draft, unit_cost: e.target.value })} onKeyDown={enter(() => go("amount"), num(draft.unit_cost) > 0)} />TL</label>
      <button className="primary-button" disabled={!(num(draft.unit_cost) > 0)} data-testid="wizard-next" onClick={() => go("amount")}>Devam</button>
    </Question>,
    amount: <Question title={`Bir ${product.name} için ne kadar ${draft.name} kullanıyorsunuz?`}>
      <label className="wiz-inline"><input autoFocus type="number" min="0" step="any" value={draft.amount} data-testid="wizard-amount-input" placeholder="0" onChange={(e) => setDraft({ ...draft, amount: e.target.value })} onKeyDown={enter(addLine, num(draft.amount) > 0)} />
        {sub ? <span className="wiz-unit-toggle">{[[true, sub[0]], [false, draft.unit]].map(([v, l]) => <button key={l} className={draft.useSub === v ? "active" : ""} data-testid={`wizard-amount-unit-${l}`} onClick={() => setDraft({ ...draft, useSub: v })}>{l}</button>)}</span> : draft.unit}</label>
      {num(draft.amount) > 0 && <small className="muted" data-testid="wizard-line-preview">= {money((sub && draft.useSub ? num(draft.amount) / sub[1] : num(draft.amount)) * num(draft.unit_cost))}</small>}
      <button className="primary-button" disabled={!(num(draft.amount) > 0)} data-testid="wizard-next" onClick={addLine}>Tarife ekle</button>
    </Question>,
    more: <Question title="Başka malzeme var mı?" hint="Ambalaj, sos, ekmek gibi küçük kalemleri de eklerseniz maliyet daha doğru çıkar.">
      <div className="wiz-yesno"><button className="primary-button" data-testid="wizard-more-yes" onClick={() => go("ingredient")}>Evet, ekle</button><button className="secondary-button" data-testid="wizard-more-no" disabled={!lines.length} onClick={() => go("margin")}>Hayır, bitti</button></div>
    </Question>,
    margin: <Question title="Bu üründen yüzde kaç kâr hedefliyorsunuz?" hint="Restoranlarda genelde %60–70 arası hedeflenir.">
      <div className="wiz-chips">{[50, 60, 65, 70, 75].map((m) => <button key={m} className={margin === m ? "active" : ""} data-testid={`wizard-margin-${m}`} onClick={() => setMargin(m)}>%{m}</button>)}</div>
      <label className="wiz-inline">%<input type="number" min="0" max="95" value={margin} data-testid="wizard-margin-input" onChange={(e) => setMargin(Math.min(95, Number(e.target.value)))} /></label>
      <p className="wiz-suggest">Önerilen satış fiyatı <strong data-testid="wizard-suggested">{money(suggested)}</strong></p>
      <button className="primary-button" data-testid="wizard-next" onClick={() => { setPrice(String(suggested)); go("price_sale"); }}>Devam</button>
    </Question>,
    price_sale: <Question title={`${product.name} kaç TL'ye satılsın?`} hint={`Önerilen: ${money(suggested)}. İsterseniz değiştirin.`}>
      <label className="wiz-inline"><input autoFocus type="number" min="0" step="any" value={price} data-testid="wizard-price-input" onChange={(e) => setPrice(e.target.value)} onKeyDown={enter(() => go("summary"), num(price) > 0)} />TL</label>
      {num(price) > 0 && <small className={(num(price) - cost) / num(price) * 100 < margin ? "danger-inline" : "green-text"} data-testid="wizard-price-margin">Bu fiyatla kâr marjı %{((num(price) - cost) / num(price) * 100).toFixed(1).replace(".", ",")} · porsiyon kârı {money(num(price) - cost)}</small>}
      <button className="primary-button" disabled={!(num(price) > 0)} data-testid="wizard-next" onClick={() => go("summary")}>Özeti gör</button>
    </Question>,
    summary: <Question title="Her şey doğru mu?">
      <div className="wiz-summary" data-testid="wizard-summary">
        <div><span>Ürün</span><b>{product.name} · {product.category}</b></div>
        <div><span>Maliyet</span><b>{money(cost)}</b></div>
        <div><span>Satış fiyatı</span><b>{money(num(price))}</b></div>
        <div><span>Kâr / marj</span><b className="green-text">{money(num(price) - cost)} · %{num(price) ? ((num(price) - cost) / num(price) * 100).toFixed(1).replace(".", ",") : 0}</b></div>
        <div><span>Gıda maliyeti</span><b>%{num(price) ? (cost / num(price) * 100).toFixed(1).replace(".", ",") : 0}</b></div>
        {lines.some((l) => l.isNew) && <p className="muted">Yeni malzemeler ({lines.filter((l) => l.isNew).map((l) => l.name).join(", ")}) üç restoranın stoğuna 0 miktarla ve girdiğiniz fiyatla açılacak.</p>}
      </div>
      <button className="primary-button" disabled={saving} data-testid="wizard-save" onClick={save}>{saving ? "Kaydediliyor…" : "Menüye kaydet"}</button>
    </Question>,
  };
  return (
    <div className="modal-backdrop">
      <div className="modal wizard-modal" data-testid="product-wizard">
        <button className="icon-button close" data-testid="wizard-close" onClick={onClose}><X size={18} /></button>
        <span className="eyebrow"><Sparkles size={12} /> SORULARLA ÜRÜN EKLE</span>
        <div className="wiz-body">
          <div className="wiz-main" key={step}>{steps[step]}{history.length > 0 && <button className="text-button wiz-back" data-testid="wizard-back" onClick={back}><ArrowLeft size={13} /> Geri</button>}</div>
          <Recap lines={lines} onRemove={(i) => setLines(lines.filter((_, idx) => idx !== i))} />
        </div>
      </div>
    </div>
  );
};

export const WizardBanner = ({ onOpen }) => (
  <button className="wizard-banner" data-testid="open-product-wizard" onClick={onOpen}>
    <Sparkles size={18} /><span><b>Sorularla ürün ekle</b><small>Ürünü ve içindekileri adım adım yazın, maliyet ve önerilen fiyat otomatik çıksın</small></span>
  </button>
);
