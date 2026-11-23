import { useEffect, useState } from "react";
import axios from "axios";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const money = (n) => new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY", maximumFractionDigits: 2 }).format(n || 0);

export default function MenuPage() {
  const [menu, setMenu] = useState(null);
  const [error, setError] = useState(false);
  useEffect(() => { document.title = "GÖKBOSS · Menü"; axios.get(`${API}/public/menu`).then(({ data }) => setMenu(data)).catch(() => setError(true)); }, []);
  return (
    <div className="qr-menu" data-testid="public-menu">
      <header><div className="brand-mark">G</div><h1>GÖKBOSS</h1><p>Menü</p></header>
      {error && <div className="empty-state">Menü yüklenemedi, lütfen tekrar deneyin.</div>}
      {menu && !menu.categories.length && <div className="empty-state">Menü yakında burada.</div>}
      {menu?.categories.map((c, i) => (
        <section key={c.category} className="qr-cat" data-testid={`menu-category-${i}`} style={{ animationDelay: `${i * 60}ms` }}>
          <h2>{c.category}</h2>
          {c.items.map((it, j) => <div className="qr-item" key={it.name} data-testid={`menu-item-${i}-${j}`}><span>{it.name}</span><i /><b>{money(it.price)}</b></div>)}
        </section>
      ))}
      <footer>Afiyet olsun</footer>
    </div>
  );
}
