import { useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Minus, Plus, X } from "lucide-react";
import { errorText } from "@/lib/restaurant";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const money = (n) => new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY", maximumFractionDigits: 2 }).format(n || 0);
const MODES = [["full", "Tamamı"], ["amount", "Tutar ile böl"], ["items", "Ürün seçerek"]];

function ItemPicker({ items, picked, setPicked }) {
  const change = (i, d) => setPicked({ ...picked, [i.product_id]: Math.min(i.quantity, Math.max(0, (picked[i.product_id] || 0) + d)) });
  return (
    <div className="pay-items" data-testid="pay-items">
      {items.map((i) => (
        <div key={i.product_id} className={`pay-item ${picked[i.product_id] ? "on" : ""}`} data-testid={`pay-item-${i.product_id}`}>
          <span><b>{i.product_name}</b><small>{i.quantity} adet hesapta · {money(i.unit_price)}</small></span>
          <div className="staff-qty"><button data-testid={`pay-item-minus-${i.product_id}`} onClick={() => change(i, -1)}><Minus size={13} /></button><span data-testid={`pay-item-qty-${i.product_id}`}>{picked[i.product_id] || 0}</span><button data-testid={`pay-item-plus-${i.product_id}`} onClick={() => change(i, 1)}><Plus size={13} /></button></div>
        </div>
      ))}
    </div>
  );
}

export const PayBox = ({ table, onPaid }) => {
  const order = table.order;
  const pending = order.pending || [];
  const left = Math.round((order.total - pending.reduce((s, p) => s + p.amount, 0)) * 100) / 100;
  const [mode, setMode] = useState("full");
  const [payment, setPayment] = useState("Nakit");
  const [tip, setTip] = useState("");
  const [amount, setAmount] = useState("");
  const [guests, setGuests] = useState(2);
  const [picked, setPicked] = useState({});
  const [busy, setBusy] = useState(false);
  const pickedItems = Object.entries(picked).filter(([, q]) => q > 0).map(([product_id, quantity]) => ({ product_id, quantity }));
  const pickedTotal = pickedItems.reduce((s, p) => s + p.quantity * (order.items.find((i) => i.product_id === p.product_id)?.unit_price || 0), 0);
  const charge = mode === "full" ? left : mode === "amount" ? Number(amount || 0) : pickedTotal;
  const run = async (fn, ok) => { setBusy(true); try { const closed = await fn(); toast.success(ok); await onPaid(Boolean(closed)); } catch (e) { toast.error(errorText(e, "Ödeme alınamadı")); } finally { setBusy(false); } };
  const pay = () => run(async () => {
    const body = { payment, tip: Number(tip || 0), ...(mode === "amount" && { amount: Number(amount) }), ...(mode === "items" && { items: pickedItems }) };
    const { data } = await axios.post(`${API}/tables/${table.id}/pay`, body);
    setTip(""); setAmount(""); setPicked({});
    return data.closed;
  }, charge >= left - 0.01 && mode !== "items" ? `Masa ${table.name} hesabı kapandı` : `${money(charge)} ${payment} ödeme alındı`);
  const remove = (p) => run(() => axios.post(`${API}/tables/${table.id}/pending/${p.id}/remove`), "Ödeme kaldırıldı");
  return (
    <div className="table-checkout" data-testid="table-paybox">
      {(pending.length > 0 || order.paid?.length > 0) && <div className="pay-history" data-testid="pay-history">
        {order.paid?.map((p) => <span key={p.id} className="pay-chip done">{p.payment} {money(p.amount)}{p.items ? ` · ${p.items.map((i) => `${i.quantity}× ${i.product_name}`).join(", ")}` : ""}</span>)}
        {pending.map((p, i) => <span key={p.id} className="pay-chip" data-testid={`pay-pending-${i}`}>{p.payment} {money(p.amount)} alındı<button title="Kaldır" data-testid={`pay-pending-remove-${i}`} onClick={() => remove(p)}><X size={11} /></button></span>)}
      </div>}
      <div className="pay-left"><span>Kalan</span><strong data-testid="table-remaining">{money(left)}</strong></div>
      <div className="pay-modes">{MODES.map(([k, l]) => <button key={k} className={mode === k ? "active" : ""} data-testid={`pay-mode-${k}`} onClick={() => setMode(k)}>{l}</button>)}</div>
      {mode === "amount" && <div className="pay-amount">
        <input type="number" min="0" step="any" placeholder="Tutar ₺" value={amount} data-testid="pay-amount-input" onChange={(e) => setAmount(e.target.value)} />
        <span className="pay-equal">Eşit böl<input type="number" min="2" max="20" value={guests} data-testid="pay-guests-input" onChange={(e) => setGuests(Number(e.target.value))} />kişi<button className="secondary-button" data-testid="pay-equal-button" onClick={() => setAmount(String(Math.ceil((order.total / Math.max(guests, 1)) * 100) / 100 > left ? left : Math.ceil((order.total / Math.max(guests, 1)) * 100) / 100))}>Doldur</button></span>
      </div>}
      {mode === "items" && <ItemPicker items={order.items} picked={picked} setPicked={setPicked} />}
      <div className="staff-channels">{["Nakit", "Kart", "Yemek kartı"].map((p) => <button key={p} className={`report-tab ${payment === p ? "active" : ""}`} data-testid={`table-payment-${p}`} onClick={() => setPayment(p)}>{p}</button>)}</div>
      <label className="tip-input">Bahşiş (₺)<input type="number" min="0" step="any" value={tip} placeholder="0" data-testid="table-tip-input" onChange={(e) => setTip(e.target.value)} /></label>
      <button className="primary-button full" disabled={busy || charge <= 0} data-testid="table-close-button" onClick={pay}>{mode === "full" ? `Hesabı kapat · ${money(left)}` : `${money(charge)} ödeme al`}</button>
    </div>
  );
};
