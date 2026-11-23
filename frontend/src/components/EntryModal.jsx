import { useState } from "react";
import { Plus, Save, Trash2, X } from "lucide-react";

function RecipeEditor({ value, inventory, onChange }) {
  const rows = value || [];
  const update = (i, patch) => onChange(rows.map((row, idx) => (idx === i ? { ...row, ...patch } : row)));
  return (
    <div className="recipe-editor" data-testid="recipe-editor">
      <span className="recipe-title">Tarif (satışta stoktan düşülür)</span>
      {!inventory.length && <small className="muted">Önce Stok Sayımı'na malzeme ekleyin.</small>}
      {rows.map((row, i) => (
        <div className="recipe-row" key={i} data-testid={`recipe-row-${i}`}>
          <select value={row.inventory_id} data-testid={`recipe-ingredient-${i}`} onChange={(e) => update(i, { inventory_id: e.target.value })}>
            <option value="">Malzeme seçin</option>
            {inventory.map((item) => <option key={item.id} value={item.id}>{item.name} ({item.unit})</option>)}
          </select>
          <input type="number" step="any" placeholder="Miktar" value={row.amount} data-testid={`recipe-amount-${i}`} onChange={(e) => update(i, { amount: e.target.value })} />
          <button type="button" className="icon-button" data-testid={`recipe-remove-${i}`} onClick={() => onChange(rows.filter((_, idx) => idx !== i))}><Trash2 size={14} /></button>
        </div>
      ))}
      {inventory.length > 0 && <button type="button" className="text-button" data-testid="recipe-add-button" onClick={() => onChange([...rows, { inventory_id: "", amount: "" }])}>+ Malzeme ekle</button>}
      <small className="muted">Tarif boşsa, ürünle aynı isimdeki stok kaleminden adet başına 1 düşülür.</small>
    </div>
  );
}

function PurchaseEditor({ value, inventory, onChange }) {
  const rows = value || [];
  const update = (i, patch) => onChange(rows.map((row, idx) => (idx === i ? { ...row, ...patch } : row)));
  const total = rows.reduce((sum, r) => sum + Number(r.quantity || 0) * Number(r.unit_price || 0), 0);
  return (
    <div className="recipe-editor" data-testid="purchase-editor">
      <span className="recipe-title">Alınan malzemeler (stoka eklenir, alış fiyatı güncellenir)</span>
      {rows.map((row, i) => (
        <div className="purchase-row" key={i} data-testid={`purchase-row-${i}`}>
          <select value={row.inventory_id} data-testid={`purchase-ingredient-${i}`} onChange={(e) => update(i, { inventory_id: e.target.value })}>
            <option value="">Malzeme seçin</option>
            {inventory.map((item) => <option key={item.id} value={item.id}>{item.name} ({item.unit})</option>)}
          </select>
          <input type="number" step="any" placeholder="Miktar" value={row.quantity} data-testid={`purchase-quantity-${i}`} onChange={(e) => update(i, { quantity: e.target.value })} />
          <input type="number" step="any" placeholder="Birim ₺" value={row.unit_price} data-testid={`purchase-price-${i}`} onChange={(e) => update(i, { unit_price: e.target.value })} />
          <button type="button" className="icon-button" data-testid={`purchase-remove-${i}`} onClick={() => onChange(rows.filter((_, idx) => idx !== i))}><Trash2 size={14} /></button>
        </div>
      ))}
      {inventory.length > 0 ? <button type="button" className="text-button" data-testid="purchase-add-button" onClick={() => onChange([...rows, { inventory_id: "", quantity: "", unit_price: "" }])}>+ Alınan malzeme ekle</button> : <small className="muted">Stok kalemi yok; önce Stok Sayımı'na malzeme ekleyin.</small>}
      {rows.length > 0 && <small className="muted" data-testid="purchase-total">Kalemler toplamı: {total.toLocaleString("tr-TR", { maximumFractionDigits: 2 })} ₺ (tutar boşsa bu kullanılır)</small>}
    </div>
  );
}

function Field({ field, value, onChange, inventory, autoFocus }) {
  if (field.type === "recipe") return <RecipeEditor value={value} inventory={inventory} onChange={onChange} />;
  if (field.type === "purchases") return <PurchaseEditor value={value} inventory={inventory} onChange={onChange} />;
  return (
    <label data-testid={`${field.key}-field`}>{field.label}
      {field.type === "select"
        ? <select value={value || ""} onChange={(e) => onChange(e.target.value)} data-testid={`${field.key}-select`}><option value="">Seçin</option>{[...field.options, ...(value && !field.options.includes(value) ? [value] : [])].map((o) => <option key={o} value={o}>{o}</option>)}</select>
        : <input autoFocus={autoFocus} type={field.type || "text"} step="any" placeholder={field.placeholder} value={value ?? ""} onChange={(e) => onChange(e.target.value)} />}
    </label>
  );
}

export const EntryModal = ({ title, fields, initial, inventory, onClose, onSave }) => {
  const [form, setForm] = useState(initial || {});
  const editing = Boolean(initial?.id);
  return (
    <div className="modal-backdrop">
      <div className="modal" data-testid="entry-modal">
        <button className="icon-button close" data-testid="close-modal-button" onClick={onClose}><X size={18} /></button>
        <span className="eyebrow">{editing ? "KAYDI DÜZENLE" : "YENİ KAYIT"}</span>
        <h2>{title}</h2>
        <div className="form-grid">
          {fields.map((field, i) => <Field key={field.key} field={field} value={form[field.key]} inventory={inventory} autoFocus={i === 0} onChange={(v) => setForm({ ...form, [field.key]: v })} />)}
        </div>
        <button className="primary-button full" data-testid="save-entry-button" onClick={() => onSave(form)}>{editing ? <><Save size={17} /> Değişiklikleri kaydet</> : <><Plus size={17} /> Kaydı ekle</>}</button>
      </div>
    </div>
  );
};
