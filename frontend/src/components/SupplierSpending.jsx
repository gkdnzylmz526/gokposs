import { useEffect, useState } from "react";
import axios from "axios";
import { BarChart3 } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const money = (n) => new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY", maximumFractionDigits: 0 }).format(n || 0);
const monthLabel = (key) => new Date(`${key}-01T12:00:00`).toLocaleDateString("tr-TR", { month: "short", year: "2-digit" });

export const SupplierSpending = ({ refreshKey }) => {
  const [data, setData] = useState({ months: [], rows: [] });
  const [months, setMonths] = useState(6);
  useEffect(() => { axios.get(`${API}/suppliers/spending`, { params: { months } }).then(({ data: d }) => setData(d)).catch(() => {}); }, [months, refreshKey]);
  const max = Math.max(1, ...data.rows.flatMap((r) => Object.values(r.months)));
  const grid = { gridTemplateColumns: `1.4fr repeat(${data.months.length}, minmax(70px, 1fr)) 1fr` };
  return (
    <section className="panel table-panel spending-panel" data-testid="supplier-spending">
      <div className="panel-head movements-head">
        <div><h3>Tedarikçi harcamaları</h3><span className="muted">Aylık alış giderleri · gider kaydındaki tedarikçiye ya da alınan malzemenin tedarikçisine göre</span></div>
        <div className="movements-filter"><BarChart3 size={18} className="panel-icon" />
          <select value={months} onChange={(e) => setMonths(Number(e.target.value))} data-testid="supplier-spending-months"><option value={3}>Son 3 ay</option><option value={6}>Son 6 ay</option><option value={12}>Son 12 ay</option></select>
        </div>
      </div>
      <div className="spending-scroll">
        <div className="table-head" style={grid}><span>Tedarikçi</span>{data.months.map((m) => <span key={m}>{monthLabel(m)}</span>)}<span>Toplam</span></div>
        {!data.rows.length && <div className="empty-state">Bu dönemde tedarikçiye bağlı gider yok. Gider eklerken tedarikçi seçin.</div>}
        {data.rows.map((r, i) => (
          <div className="table-row" style={grid} key={r.supplier} data-testid={`supplier-spending-row-${i}`}>
            <span><b>{r.supplier}</b><small className="muted block">{r.count} alış</small></span>
            {data.months.map((m) => <span key={m} className="spend-cell"><i style={{ width: `${(r.months[m] / max) * 100}%` }} />{r.months[m] ? money(r.months[m]) : "—"}</span>)}
            <span className="table-amount">{money(r.total)}</span>
          </div>
        ))}
      </div>
    </section>
  );
};
