import { useEffect, useState } from "react";
import axios from "axios";
import { Award, LineChart } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const money = (n) => new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY", maximumFractionDigits: 2 }).format(n || 0);
const day = (d) => new Date(d).toLocaleDateString("tr-TR", { day: "2-digit", month: "2-digit" });

function PriceChart({ history }) {
  if (history.length < 2) return <div className="empty-state small">Grafik için en az 2 alış gerekli.</div>;
  const W = 560, H = 150, P = 28, L = 66;
  const prices = history.map((h) => h.unit_price);
  const min = Math.min(...prices), max = Math.max(...prices), span = max - min || 1;
  const pts = history.map((h, i) => [L + (i * (W - L - P)) / (history.length - 1), H - P - ((h.unit_price - min) / span) * (H - 2 * P)]);
  const path = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="price-chart" data-testid="price-chart">
      <line x1={L} x2={W - P} y1={H - P} y2={H - P} className="axis" />
      <text x={L - 8} y={P + 3} textAnchor="end" className="lbl">{money(max)}</text><text x={L - 8} y={H - P + 3} textAnchor="end" className="lbl">{money(min)}</text>
      <path d={`${path} L${pts[pts.length - 1][0]},${H - P} L${pts[0][0]},${H - P} Z`} className="area" />
      <path d={path} className="line" />
      {pts.map((p, i) => <g key={i}><circle cx={p[0]} cy={p[1]} r="4" className="dot"><title>{`${day(history[i].date)} · ${money(history[i].unit_price)} · ${history[i].supplier}`}</title></circle>{(i === 0 || i === pts.length - 1 || history.length <= 8) && <text x={p[0]} y={H - 8} textAnchor="middle" className="lbl">{day(history[i].date)}</text>}</g>)}
    </svg>
  );
}

export const PriceInsights = ({ inventory, refreshKey }) => {
  const [selected, setSelected] = useState("");
  const [data, setData] = useState(null);
  const current = selected || inventory[0]?.id || "";
  useEffect(() => { if (!current) return setData(null); axios.get(`${API}/inventory/${current}/prices`).then(({ data: d }) => setData(d)).catch(() => setData(null)); }, [current, refreshKey]);
  if (!inventory.length) return null;
  const first = data?.history[0]?.unit_price, last = data?.history[data.history.length - 1]?.unit_price;
  const change = first && last ? Math.round(((last - first) / first) * 1000) / 10 : 0;
  const cheapest = data?.comparison[0];
  return (
    <section className="panel price-insights" data-testid="price-insights">
      <div className="panel-head">
        <div><h3>Fiyat geçmişi & tedarikçi karşılaştırması</h3><span className="muted">Alış giderlerinde girilen birim fiyatlardan</span></div>
        <div className="movements-filter"><LineChart size={18} className="panel-icon" />
          <select value={current} onChange={(e) => setSelected(e.target.value)} data-testid="price-insights-select">{inventory.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}</select>
        </div>
      </div>
      {!data?.history.length ? <div className="empty-state">Bu malzeme için birim fiyatlı alış kaydı yok. Gider eklerken "Alınan malzemeler" bölümüne fiyat girin.</div> : (
        <div className="insights-grid">
          <div>
            <div className="insight-stats">
              <span>Son fiyat<b data-testid="price-last">{money(last)}</b></span>
              <span>İlk kayda göre<b className={change > 0 ? "up" : change < 0 ? "down" : ""} data-testid="price-change">{`${change > 0 ? "+" : change < 0 ? "−" : ""}%${Math.abs(change).toLocaleString("tr-TR")}`}</b></span>
              <span>Alış sayısı<b>{data.history.length}</b></span>
            </div>
            <PriceChart history={data.history} />
          </div>
          <div className="compare-list">
            {data.comparison.map((r, i) => (
              <div key={r.supplier} className={`compare-row ${i === 0 && data.comparison.length > 1 ? "best" : ""}`} data-testid={`price-compare-row-${i}`}>
                <div><b>{r.supplier}{i === 0 && data.comparison.length > 1 && <em><Award size={11} /> En ucuz</em>}</b><small>{r.purchases} alış · ort. {money(r.avg_price)} · en düşük {money(r.min_price)}</small></div>
                <strong>{money(r.last_price)}<small>/{data.item.unit}</small></strong>
              </div>
            ))}
            {data.comparison.length > 1 && cheapest && <small className="muted" data-testid="price-saving">En pahalıya göre {money(data.comparison[data.comparison.length - 1].last_price - cheapest.last_price)}/{data.item.unit} tasarruf</small>}
          </div>
        </div>
      )}
    </section>
  );
};
