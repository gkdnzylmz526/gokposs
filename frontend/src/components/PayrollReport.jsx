import { useEffect, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Download, Wallet } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const money = (n) => new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY", maximumFractionDigits: 2 }).format(n || 0);
const num = (n) => Number(Number(n || 0).toFixed(2)).toLocaleString("tr-TR");
const monthOptions = () => Array.from({ length: 12 }, (_, i) => { const d = new Date(); d.setDate(1); d.setMonth(d.getMonth() - i); return d.toLocaleDateString("sv-SE").slice(0, 7); });
const monthLabel = (m) => new Date(`${m}-01T12:00:00`).toLocaleDateString("tr-TR", { month: "long", year: "numeric" });

export const PayrollReport = ({ refreshKey }) => {
  const months = monthOptions();
  const [month, setMonth] = useState(months[0]);
  const [data, setData] = useState(null);
  useEffect(() => { axios.get(`${API}/payroll`, { params: { month } }).then(({ data: d }) => setData(d)).catch(() => setData(null)); }, [month, refreshKey]);
  const download = async () => {
    try {
      const { data: blob } = await axios.get(`${API}/payroll/export`, { params: { month }, responseType: "blob" });
      const link = document.createElement("a"); link.href = URL.createObjectURL(blob); link.download = `gokboss-pos-maas-${month}.xlsx`;
      document.body.appendChild(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(link.href), 1000);
      toast.success("Maaş raporu indirildi");
    } catch { toast.error("Maaş raporu indirilemedi"); }
  };
  const grid = { gridTemplateColumns: "1.4fr .7fr .9fr .9fr 1fr 1fr 1fr" };
  return (
    <section className="panel table-panel payroll-panel" data-testid="payroll-report">
      <div className="panel-head movements-head">
        <div><h3>Aylık maaş raporu</h3><span className="muted">Vardiya takviminden · haftalık {data?.weekly_limit || 45} saati aşan çalışma fazla mesai (x{data?.overtime_rate || 1.5})</span></div>
        <div className="movements-filter"><Wallet size={18} className="panel-icon" />
          <select value={month} onChange={(e) => setMonth(e.target.value)} data-testid="payroll-month-select">{months.map((m) => <option key={m} value={m}>{monthLabel(m)}</option>)}</select>
          <button className="primary-button" data-testid="payroll-export-button" onClick={download}><Download size={15} /> Excel indir</button>
        </div>
      </div>
      <div className="spending-scroll">
        <div className="table-head" style={grid}><span>Personel</span><span>Vardiya</span><span>Normal saat</span><span>Fazla mesai</span><span>Normal ücret</span><span>Fazla mesai ücreti</span><span>Toplam</span></div>
        {!data?.rows.length && <div className="empty-state">Personel kaydı yok.</div>}
        {data?.rows.map((r, i) => (
          <div className="table-row" style={grid} key={r.staff_id} data-testid={`payroll-row-${i}`}>
            <span><b>{r.name}</b><small className="muted block">{r.hourly_wage ? `${money(r.hourly_wage)}/saat` : "Saatlik ücret girilmemiş"}</small></span>
            <span>{r.shift_count}</span><span>{num(r.regular_hours)} sa</span>
            <span className={r.overtime_hours ? "ot-text" : ""}>{num(r.overtime_hours)} sa</span>
            <span>{money(r.regular_pay)}</span><span className={r.overtime_pay ? "ot-text" : ""}>{money(r.overtime_pay)}</span>
            <span className="table-amount" data-testid={`payroll-total-${i}`}>{money(r.total_pay)}</span>
          </div>
        ))}
        {data?.rows.length > 0 && (
          <div className="table-row payroll-total-row" style={grid} data-testid="payroll-totals">
            <span><b>Toplam</b></span><span /><span>{num(data.totals.regular_hours)} sa</span><span>{num(data.totals.overtime_hours)} sa</span>
            <span>{money(data.totals.regular_pay)}</span><span>{money(data.totals.overtime_pay)}</span><span className="table-amount">{money(data.totals.total_pay)}</span>
          </div>
        )}
      </div>
    </section>
  );
};
