import { useEffect, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { ArrowDown, ArrowUp, ChevronDown, GripVertical, Save, X } from "lucide-react";
import { errorText } from "@/lib/restaurant";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const move = (list, from, to) => { if (to < 0 || to >= list.length || from === to) return list; const copy = [...list]; const [it] = copy.splice(from, 1); copy.splice(to, 0, it); return copy; };

function SortRow({ label, index, count, onMove, drag, testId, children, extra }) {
  return (
    <div className={`sort-row ${drag.over === index ? "drag-over" : ""}`} draggable onDragStart={(e) => { e.stopPropagation(); drag.start(index); }} onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); drag.enter(index); }} onDrop={(e) => { e.preventDefault(); e.stopPropagation(); drag.drop(index); }} onDragEnd={drag.end} data-testid={testId}>
      <div className="sort-line">
        <GripVertical size={16} className="sort-grip" />
        <span className="sort-label">{label}</span>{extra}
        <button type="button" aria-label="Yukarı" disabled={index === 0} onClick={() => onMove(index, index - 1)} data-testid={`${testId}-up`}><ArrowUp size={14} /></button>
        <button type="button" aria-label="Aşağı" disabled={index === count - 1} onClick={() => onMove(index, index + 1)} data-testid={`${testId}-down`}><ArrowDown size={14} /></button>
      </div>
      {children}
    </div>
  );
}

const useDrag = (onMove) => {
  const [from, setFrom] = useState(null);
  const [over, setOver] = useState(null);
  return { over, start: setFrom, enter: setOver, drop: (to) => { if (from !== null) onMove(from, to); setFrom(null); setOver(null); }, end: () => { setFrom(null); setOver(null); } };
};

function ProductList({ items, onChange, catIndex }) {
  const moveItem = (a, b) => onChange(move(items, a, b));
  const drag = useDrag(moveItem);
  return <div className="sort-children">{items.map((p, j) => <SortRow key={p.id} label={p.name} index={j} count={items.length} onMove={moveItem} drag={drag} testId={`order-product-${catIndex}-${j}`} />)}</div>;
}

export const MenuOrder = ({ onClose, onSaved }) => {
  const [cats, setCats] = useState(null);
  const [openCat, setOpenCat] = useState(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => { axios.get(`${API}/menu-order`).then(({ data }) => setCats(data)).catch(() => toast.error("Menü yüklenemedi")); }, []);
  const moveCat = (a, b) => { setCats((c) => move(c, a, b)); setOpenCat((o) => (o === a ? b : o)); };
  const drag = useDrag(moveCat);
  const save = async () => {
    setSaving(true);
    try { await axios.put(`${API}/menu-order`, { categories: cats.map((c) => c.category), products: cats.flatMap((c) => c.items.map((i) => i.id)) }); toast.success("Menü sırası kaydedildi, QR menü güncellendi"); onSaved?.(); onClose(); }
    catch (e) { toast.error(errorText(e, "Kaydedilemedi")); } finally { setSaving(false); }
  };
  return (
    <div className="sort-overlay" onClick={onClose}>
      <div className="sort-modal panel" onClick={(e) => e.stopPropagation()} data-testid="menu-order-modal">
        <div className="panel-head"><div><h3>Menü sırası</h3><span className="muted">Sürükleyip bırakın ya da oklarla taşıyın. Ürünleri görmek için kategoriye tıklayın.</span></div><button className="chat-icon" onClick={onClose} aria-label="Kapat" data-testid="menu-order-close"><X size={18} /></button></div>
        <div className="sort-list">
          {!cats ? <div className="loading-state">Yükleniyor…</div> : cats.map((c, i) => (
            <SortRow key={c.category} label={<button type="button" className="sort-cat" onClick={() => setOpenCat(openCat === i ? null : i)} data-testid={`order-category-toggle-${i}`}>{c.category} <small>{c.items.length} ürün</small><ChevronDown size={14} className={openCat === i ? "rot" : ""} /></button>} index={i} count={cats.length} onMove={moveCat} drag={drag} testId={`order-category-${i}`}>
              {openCat === i && <ProductList items={c.items} catIndex={i} onChange={(items) => setCats((all) => all.map((x, k) => (k === i ? { ...x, items } : x)))} />}
            </SortRow>
          ))}
        </div>
        <div className="rest-form-actions"><button className="text-button" onClick={onClose}>Vazgeç</button><button className="primary-button" disabled={!cats || saving} onClick={save} data-testid="menu-order-save"><Save size={15} /> {saving ? "Kaydediliyor…" : "Sırayı kaydet"}</button></div>
      </div>
    </div>
  );
};
