import { useEffect, useState } from "react";
import axios from "axios";
import { History } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const LABELS = { sales: "Satış", expenses: "Gider", inventory: "Stok", staff: "Personel", cash: "Kasa", products: "Menü", suppliers: "Tedarikçi", shifts: "Vardiya", leaves: "İzin", advances: "Avans", orders: "Sipariş", leave_requests: "İzin talebi" };

export const AuditLog = () => {
  const [logs, setLogs] = useState([]);
  const [collection, setCollection] = useState("");
  const [user, setUser] = useState("");
  useEffect(() => { axios.get(`${API}/audit-logs`, { params: { ...(collection && { collection }), ...(user && { user_email: user }) } }).then(({ data }) => setLogs(data)).catch(() => setLogs([])); }, [collection, user]);
  const [users, setUsers] = useState([]);
  useEffect(() => { axios.get(`${API}/users`).then(({ data }) => setUsers(data.users.map((u) => u.email).filter(Boolean))).catch(() => {}); }, []);
  const grid = { gridTemplateColumns: "1fr 1.3fr .7fr .8fr 2.4fr" };
  return (
    <section className="panel table-panel audit-panel" data-testid="audit-log">
      <div className="panel-head movements-head">
        <div><h3>İşlem geçmişi</h3><span className="muted">Kim, ne zaman, hangi kaydı ekledi, değiştirdi veya sildi</span></div>
        <div className="movements-filter"><History size={18} className="panel-icon" />
          <select value={collection} onChange={(e) => setCollection(e.target.value)} data-testid="audit-filter-collection"><option value="">Tüm kayıtlar</option>{Object.entries(LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
          <select value={user} onChange={(e) => setUser(e.target.value)} data-testid="audit-filter-user"><option value="">Tüm kullanıcılar</option>{users.map((u) => <option key={u}>{u}</option>)}</select>
        </div>
      </div>
      <div className="spending-scroll">
        <div className="table-head" style={grid}><span>Tarih</span><span>Kullanıcı</span><span>İşlem</span><span>Bölüm</span><span>Detay</span></div>
        {!logs.length && <div className="empty-state">Henüz kayıtlı işlem yok.</div>}
        {logs.map((l, i) => (
          <div className="table-row" style={grid} key={l.id} data-testid={`audit-row-${i}`}>
            <span>{new Date(l.created_at).toLocaleString("tr-TR", { dateStyle: "short", timeStyle: "short" })}</span>
            <span>{l.user_email || "—"}{l.role === "staff" && <em className="recipe-badge">personel</em>}</span>
            <span><em className={`audit-action a-${l.action === "Sildi" ? "del" : l.action === "Ekledi" ? "add" : "edit"}`}>{l.action}</em></span>
            <span>{LABELS[l.collection] || l.collection}</span>
            <span className="audit-summary">{l.summary}</span>
          </div>
        ))}
      </div>
    </section>
  );
};
