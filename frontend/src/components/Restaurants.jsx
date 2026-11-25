import { useEffect, useState } from "react";
import axios from "axios";
import { Lock, Store } from "lucide-react";
import { RESTAURANTS } from "@/lib/restaurant";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const money = (n) => new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY", maximumFractionDigits: 0 }).format(n || 0);

export const RestaurantSwitcher = ({ value, onChange }) => (
  <label className="restaurant-switcher" data-testid="restaurant-switcher">
    <Store size={16} />
    <select value={value} onChange={(e) => onChange(e.target.value)} data-testid="restaurant-select">
      {RESTAURANTS.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
      <option value="all">Tüm restoranlar (toplam)</option>
    </select>
  </label>
);

export const AllModeBanner = () => (
  <div className="all-mode-banner" data-testid="all-mode-banner">Tüm restoranların toplamını görüyorsunuz. Kayıt eklemek veya düzenlemek için üstten bir restoran seçin.</div>
);

export const RestaurantSummary = ({ refreshKey, active, onPick }) => {
  const [rows, setRows] = useState([]);
  useEffect(() => { axios.get(`${API}/restaurants/summary`).then(({ data }) => setRows(data)).catch(() => setRows([])); }, [refreshKey]);
  if (!rows.length) return null;
  return (
    <section className="restaurant-summary" data-testid="restaurant-summary">
      {rows.map((r) => r.locked ? (
        <button key={r.id} className={`restaurant-card locked ${active === r.id ? "active" : ""}`} data-testid={`restaurant-card-${r.id}`} onClick={() => onPick(r.id)}>
          <span className="eyebrow">{r.name.toLocaleUpperCase("tr-TR")}</span>
          <strong><Lock size={18} /> Kilitli</strong>
          <small>Rakamları görmek için tıklayıp şifreyi girin</small>
        </button>
      ) : (
        <button key={r.id} className={`restaurant-card ${active === r.id ? "active" : ""}`} data-testid={`restaurant-card-${r.id}`} onClick={() => onPick(r.id)}>
          <span className="eyebrow">{r.name.toLocaleUpperCase("tr-TR")}</span>
          <strong data-testid={`restaurant-today-${r.id}`}>{money(r.today_revenue)}</strong>
          <small>Bugün · {r.today_sales} satış · kâr <b className={r.today_profit < 0 ? "danger-inline" : "green-text"}>{money(r.today_profit)}</b></small>
          <div className="restaurant-card-foot"><span>Son 30 gün {money(r.month_revenue)}</span><span>{r.open_tables} açık masa</span><span className={r.low_stock ? "danger-inline" : ""}>{r.low_stock} kritik stok</span></div>
        </button>
      ))}
    </section>
  );
};
