import { useEffect, useState } from "react";
import axios from "axios";
import { ArrowLeft, UtensilsCrossed } from "lucide-react";

const BASE = process.env.REACT_APP_BACKEND_URL;
const money = (n) => new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY", maximumFractionDigits: 2 }).format(n || 0);

function CategoryGrid({ categories, onPick }) {
  return (
    <div className="qr-cat-grid" data-testid="menu-category-grid">
      {categories.map((c, i) => (
        <button key={c.category} className={`qr-cat-card ${c.cover ? "has-cover" : ""}`} data-testid={`menu-category-${i}`} style={{ animationDelay: `${i * 60}ms` }} onClick={() => onPick(i)}>
          {c.cover ? <img src={`${BASE}${c.cover}`} alt={c.category} loading="lazy" /> : <UtensilsCrossed size={26} />}
          <span><b>{c.category}</b><small>{c.count} ürün</small></span>
        </button>
      ))}
    </div>
  );
}

function CategoryItems({ category, index, onZoom }) {
  return (
    <section className="qr-cat" data-testid={`menu-category-items-${index}`}>
      <h2>{category.category}</h2>
      {category.items.map((it, j) => (
        <div className={`qr-item ${it.photo_url ? "with-photo" : ""}`} key={it.name} data-testid={`menu-item-${index}-${j}`}>
          {it.photo_url && <button className="qr-thumb" data-testid={`menu-photo-${index}-${j}`} onClick={() => onZoom(it)}><img src={`${BASE}${it.photo_url}`} alt={it.name} loading="lazy" /></button>}
          <div className="qr-text"><div className="qr-line"><span>{it.name}</span><i /><b>{money(it.price)}</b></div>{it.description && <small>{it.description}</small>}</div>
        </div>
      ))}
    </section>
  );
}

export default function MenuPage() {
  const [menu, setMenu] = useState(null);
  const [error, setError] = useState(false);
  const [zoom, setZoom] = useState(null);
  const [active, setActive] = useState(null);
  useEffect(() => { document.title = "GÖKBOSS · Menü"; axios.get(`${BASE}/api/public/menu`).then(({ data }) => setMenu(data)).catch(() => setError(true)); }, []);
  useEffect(() => { const onPop = () => setActive(null); window.addEventListener("popstate", onPop); return () => window.removeEventListener("popstate", onPop); }, []);
  const pick = (i) => { if (active === null) window.history.pushState({ cat: i }, ""); setActive(i); window.scrollTo({ top: 0, behavior: "smooth" }); };
  const back = () => { if (window.history.state?.cat !== undefined) window.history.back(); else setActive(null); };
  const cats = menu?.categories || [];
  return (
    <div className="qr-menu" data-testid="public-menu">
      <header><div className="brand-mark">G</div><h1>GÖKBOSS</h1><p>{active === null ? "Menü · bir kategori seçin" : "Menü"}</p></header>
      {error && <div className="empty-state">Menü yüklenemedi, lütfen tekrar deneyin.</div>}
      {menu && !cats.length && <div className="empty-state">Menü yakında burada.</div>}
      {active === null ? <CategoryGrid categories={cats} onPick={pick} /> : (
        <>
          <nav className="qr-cat-tabs" data-testid="menu-category-tabs">
            <button className="qr-back" data-testid="menu-back" onClick={back}><ArrowLeft size={15} /> Kategoriler</button>
            {cats.map((c, i) => <button key={c.category} className={active === i ? "active" : ""} data-testid={`menu-tab-${i}`} onClick={() => pick(i)}>{c.category}</button>)}
          </nav>
          <CategoryItems key={active} category={cats[active]} index={active} onZoom={setZoom} />
        </>
      )}
      <footer>Afiyet olsun</footer>
      {zoom && <div className="qr-zoom" data-testid="menu-photo-zoom" onClick={() => setZoom(null)}><img src={`${BASE}${zoom.photo_url}`} alt={zoom.name} /><p><b>{zoom.name}</b> · {money(zoom.price)}{zoom.description && <small>{zoom.description}</small>}</p></div>}
    </div>
  );
}
