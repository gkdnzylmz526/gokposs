import { useEffect, useRef, useState } from "react";
import axios from "axios";
import { ArrowLeft, ChefHat, UtensilsCrossed } from "lucide-react";
import { MenuChat } from "@/components/MenuChat";
import { MENU_FILTERS, MENU_LANGS, MENU_TEXT, initialMenuLang } from "@/lib/menuI18n";
import { TagIcons } from "@/lib/menuTags";

const BASE = process.env.REACT_APP_BACKEND_URL;
const HERO = "https://customer-assets-39nsmqrw.emergentagent.net/job_restoran-asistan--8vayy60i/artifacts/517d09d772f8ef18_WhatsApp%20Image%202026-11-25%20at%2017.37.25.jpeg";
const money = (n) => new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY", maximumFractionDigits: 2 }).format(n || 0);

function LangSwitch({ lang, onChange }) {
  return <div className="qr-lang" data-testid="menu-lang-switch">{MENU_LANGS.map((l) => <button key={l.code} title={l.name} className={lang === l.code ? "active" : ""} onClick={() => onChange(l.code)} data-testid={`menu-lang-${l.code}`}>{l.label}</button>)}</div>;
}

function FilterBar({ value, onChange, t }) {
  return (
    <div className="qr-filters" data-testid="menu-filter-bar">
      <button className={value ? "" : "active"} onClick={() => onChange(null)} data-testid="menu-filter-all">{t.all}</button>
      {Object.keys(MENU_FILTERS).map((k) => <button key={k} className={value === k ? "active" : ""} onClick={() => onChange(value === k ? null : k)} data-testid={`menu-filter-${k}`}>{t.filters[k]}</button>)}
    </div>
  );
}

function ChefPickBanner({ pick, t, lang, onOpen }) {
  return (
    <button className="qr-chef-pick" onClick={onOpen} data-testid="menu-chef-pick">
      {pick.photo_url ? <img src={`${BASE}${pick.photo_url}`} alt={pick.name} /> : <span className="qr-chef-icon"><ChefHat size={30} /></span>}
      <span className="qr-chef-body">
        <small className="qr-chef-label"><ChefHat size={13} /> {t.chefPick}</small>
        <b data-testid="menu-chef-pick-name">{pick.name}</b>
        {pick.note && <em data-testid="menu-chef-pick-note">{pick.note}</em>}
        <span className="qr-chef-foot"><strong>{money(pick.price)}</strong><TagIcons tags={pick.tags} lang={lang} /></span>
      </span>
    </button>
  );
}

function CategoryGrid({ categories, onPick, t }) {
  return (
    <div className="qr-cat-grid" data-testid="menu-category-grid">
      {categories.map((c, i) => (
        <button key={c.category} className={`qr-cat-card ${c.cover ? "has-cover" : ""} ${c.count ? "" : "dim"}`} data-testid={`menu-category-${i}`} style={{ animationDelay: `${i * 60}ms` }} onClick={() => onPick(i)}>
          {c.cover ? <img src={`${BASE}${c.cover}`} alt={c.category} loading="lazy" /> : <UtensilsCrossed size={26} />}
          <span><b>{c.category}</b><small>{c.count} {c.count === 1 && t.item ? t.item : t.items}</small></span>
        </button>
      ))}
    </div>
  );
}

function CategoryItems({ category, index, onZoom, dir, lang, t }) {
  const used = [...new Set(category.items.flatMap((it) => it.tags || []))];
  return (
    <section className={`qr-cat qr-slide-${dir}`} data-testid={`menu-category-items-${index}`}>
      <h2>{category.category}</h2>
      {!category.items.length && <p className="qr-no-match" data-testid="menu-no-match">{t.noMatch}</p>}
      {category.items.map((it, j) => (
        <div className={`qr-item ${it.photo_url ? "with-photo" : ""}`} key={it.name} data-testid={`menu-item-${index}-${j}`} style={{ animationDelay: `${120 + j * 45}ms` }}>
          {it.photo_url && <button className="qr-thumb" data-testid={`menu-photo-${index}-${j}`} onClick={() => onZoom(it)}><img src={`${BASE}${it.photo_url}`} alt={it.name} loading="lazy" /></button>}
          <div className="qr-text"><div className="qr-line"><span>{it.name}{it.name_original && it.name_original.toLocaleLowerCase("tr-TR") !== it.name.toLocaleLowerCase("tr-TR") && <em className="qr-orig">{it.name_original}</em>}</span><i /><b>{money(it.price)}</b></div>{it.description && <small>{it.description}</small>}<TagIcons tags={it.tags} lang={lang} /></div>
        </div>
      ))}
      {used.length > 0 && <div className="qr-tag-legend" data-testid={`menu-tag-legend-${index}`}><TagIcons tags={used} lang={lang} withLabel /></div>}
    </section>
  );
}

export default function MenuPage() {
  const [menu, setMenu] = useState(null);
  const [error, setError] = useState(false);
  const [zoom, setZoom] = useState(null);
  const [active, setActive] = useState(null);
  const [lang, setLang] = useState(initialMenuLang);
  const [loadingLang, setLoadingLang] = useState(false);
  const t = MENU_TEXT[lang];
  const [dir, setDir] = useState("up");
  const [filter, setFilter] = useState(null);
  const touch = useRef(null);
  useEffect(() => { document.title = "Florya Dürüm Tır · Menü"; }, []);
  useEffect(() => {
    localStorage.setItem("menu-lang", lang);
    document.documentElement.lang = lang;
    setLoadingLang(true);
    axios.get(`${BASE}/api/public/menu`, { params: { lang } }).then(({ data }) => { setMenu(data); setError(false); }).catch(() => setError(true)).finally(() => setLoadingLang(false));
  }, [lang]);
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
  const test = filter && MENU_FILTERS[filter];
  const cats = (menu?.categories || []).map((c) => (test ? (({ items }) => ({ ...c, items, count: items.length }))({ items: c.items.filter((it) => test(it.tags || [])) }) : c));
  const hasTags = (menu?.categories || []).some((c) => c.items.some((it) => it.tags?.length));
  const filterBar = hasTags && <FilterBar value={filter} onChange={setFilter} t={t} />;
  return (
    <div className={`qr-menu lang-${lang}`} dir={lang === "ar" ? "rtl" : "ltr"} data-testid="public-menu">
      <LangSwitch lang={lang} onChange={setLang} />
      <header className={`qr-hero ${active === null ? "" : "compact"}`} data-testid="menu-hero">
        <img src={HERO} alt="Florya Dürüm Tır" />
        <div className="qr-hero-text">{active === null && <p className="qr-welcome" data-testid="menu-welcome">{t.welcome}</p>}<span className="qr-hero-kicker">{t.kicker}</span><h1 data-testid="menu-title">Florya <em>Dürüm</em> Tır</h1><p className="qr-hero-menu">{t.menu}</p>{active === null && <small>{loadingLang ? t.translating : t.pick}</small>}</div>
      </header>
      {error && <div className="empty-state">{t.error}</div>}
      {menu && !cats.length && <div className="empty-state">{t.empty}</div>}
      {active === null ? <div className="qr-fade-in" key="grid">{menu?.chef_pick && <ChefPickBanner pick={menu.chef_pick} t={t} lang={lang} onOpen={() => pick(menu.chef_pick.category_index)} />}{filterBar}<CategoryGrid categories={cats} onPick={pick} t={t} /></div> : (
        <>
          <nav className="qr-cat-tabs" data-testid="menu-category-tabs">
            <button className="qr-back" data-testid="menu-back" onClick={back}><ArrowLeft size={15} className="qr-back-icon" /> {t.back}</button>
            {cats.map((c, i) => <button key={c.category} className={active === i ? "active" : ""} data-testid={`menu-tab-${i}`} onClick={() => pick(i)}>{c.category}</button>)}
          </nav>
          {filterBar}
          <div className="qr-swipe" onTouchStart={onTouchStart} onTouchEnd={onTouchEnd} data-testid="menu-swipe-area"><CategoryItems key={active} lang={lang} category={cats[active]} index={active} onZoom={setZoom} dir={dir} t={t} /></div>
          {cats.length > 1 && <p className="qr-swipe-hint">{t.swipe}</p>}
        </>
      )}
      <footer>{t.footer}</footer>
      <MenuChat key={lang} t={t.chat} />
      {zoom && <div className="qr-zoom" data-testid="menu-photo-zoom" onClick={() => setZoom(null)}><img src={`${BASE}${zoom.photo_url}`} alt={zoom.name} /><p><b>{zoom.name}</b> · {money(zoom.price)}{zoom.description && <small>{zoom.description}</small>}</p></div>}
    </div>
  );
}
