import { useEffect, useRef, useState } from "react";
import axios from "axios";
import { ArrowLeft, UtensilsCrossed } from "lucide-react";
import { MenuChat } from "@/components/MenuChat";

const BASE = process.env.REACT_APP_BACKEND_URL;
const HERO = "https://customer-assets-39nsmqrw.emergentagent.net/job_restoran-asistan--8vayy60i/artifacts/517d09d772f8ef18_WhatsApp%20Image%202026-11-25%20at%2017.37.25.jpeg";
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

function CategoryItems({ category, index, onZoom, dir }) {
  return (
    <section className={`qr-cat qr-slide-${dir}`} data-testid={`menu-category-items-${index}`}>
      <h2>{category.category}</h2>
      {category.items.map((it, j) => (
        <div className={`qr-item ${it.photo_url ? "with-photo" : ""}`} key={it.name} data-testid={`menu-item-${index}-${j}`} style={{ animationDelay: `${120 + j * 45}ms` }}>
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
  const [dir, setDir] = useState("up");
  const touch = useRef(null);
  useEffect(() => { document.title = "Florya Dürüm Tır · Menü"; axios.get(`${BASE}/api/public/menu`).then(({ data }) => setMenu(data)).catch(() => setError(true)); }, []);
  useEffect(() => { const onPop = () => setActive(null); window.addEventListener("popstate", onPop); return () => window.removeEventListener("popstate", onPop); }, []);
  const pick = (i) => {
    if (i === active) return;
    if (active === null) window.history.pushState({ cat: i }, "");
    setDir(active === null ? "up" : i > active ? "left" : "right");
    setActive(i);
    window.scrollTo({ top: 0, behavior: "smooth" });
    document.querySelector(`[data-testid="menu-tab-${i}"]`)?.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
  };
  const onTouchStart = (e) => { touch.current = { x: e.touches[0].clientX, y: e.touches[0].clientY }; };
  const onTouchEnd = (e) => {
    if (!touch.current || active === null) return;
    const dx = e.changedTouches[0].clientX - touch.current.x, dy = e.changedTouches[0].clientY - touch.current.y;
    touch.current = null;
    if (Math.abs(dx) < 60 || Math.abs(dy) > Math.abs(dx)) return;
    const next = active + (dx < 0 ? 1 : -1);
    if (next >= 0 && next < cats.length) pick(next);
  };
  const back = () => { if (window.history.state?.cat !== undefined) window.history.back(); else setActive(null); };
  const cats = menu?.categories || [];
  return (
    <div className="qr-menu" data-testid="public-menu">
      <header className={`qr-hero ${active === null ? "" : "compact"}`} data-testid="menu-hero">
        <img src={HERO} alt="Florya Dürüm Tır" />
        <div className="qr-hero-text">{active === null && <p className="qr-welcome" data-testid="menu-welcome">Restoranımıza hoş geldiniz</p>}<span className="qr-hero-kicker">— Taş fırın · Dürüm · Lahmacun —</span><h1 data-testid="menu-title">Florya <em>Dürüm</em> Tır</h1><p className="qr-hero-menu">M E N Ü</p>{active === null && <small>Bir kategori seçin</small>}</div>
      </header>
      {error && <div className="empty-state">Menü yüklenemedi, lütfen tekrar deneyin.</div>}
      {menu && !cats.length && <div className="empty-state">Menü yakında burada.</div>}
      {active === null ? <div className="qr-fade-in" key="grid"><CategoryGrid categories={cats} onPick={pick} /></div> : (
        <>
          <nav className="qr-cat-tabs" data-testid="menu-category-tabs">
            <button className="qr-back" data-testid="menu-back" onClick={back}><ArrowLeft size={15} /> Kategoriler</button>
            {cats.map((c, i) => <button key={c.category} className={active === i ? "active" : ""} data-testid={`menu-tab-${i}`} onClick={() => pick(i)}>{c.category}</button>)}
          </nav>
          <div className="qr-swipe" onTouchStart={onTouchStart} onTouchEnd={onTouchEnd} data-testid="menu-swipe-area"><CategoryItems key={active} category={cats[active]} index={active} onZoom={setZoom} dir={dir} /></div>
          {cats.length > 1 && <p className="qr-swipe-hint">Kategoriler arasında kaydırarak da geçebilirsiniz</p>}
        </>
      )}
      <footer>Afiyet olsun</footer>
      <MenuChat />
      {zoom && <div className="qr-zoom" data-testid="menu-photo-zoom" onClick={() => setZoom(null)}><img src={`${BASE}${zoom.photo_url}`} alt={zoom.name} /><p><b>{zoom.name}</b> · {money(zoom.price)}{zoom.description && <small>{zoom.description}</small>}</p></div>}
    </div>
  );
}
