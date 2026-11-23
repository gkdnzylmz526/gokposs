import axios from "axios";
import { toast } from "sonner";
import { Check, Inbox, X } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const fmt = (d) => new Date(`${d}T12:00:00`).toLocaleDateString("tr-TR", { day: "numeric", month: "short" });

export const LeaveRequests = ({ requests, staff, onReload }) => {
  const pending = requests.filter((r) => r.status === "Bekliyor");
  const decided = requests.filter((r) => r.status !== "Bekliyor").slice(0, 6);
  const name = (id) => staff.find((p) => p.id === id)?.name || "—";
  const decide = async (r, decision) => {
    try { const { data } = await axios.post(`${API}/leave-requests/${r.id}/${decision}`); await onReload(); toast.success(decision === "approve" ? `Onaylandı · ${data.created} gün takvime eklendi` : "Talep reddedildi"); }
    catch (e) { toast.error(e.response?.data?.detail || "İşlem yapılamadı"); }
  };
  const Row = ({ r, i, actions }) => (
    <div className={`request-row ${r.status === "Bekliyor" ? "" : "decided"}`} data-testid={`leave-req-row-${r.id}`}>
      <span><b>{name(r.staff_id)}</b><small>{fmt(r.start)}{r.end !== r.start ? ` – ${fmt(r.end)}` : ""} · {r.days} gün · {r.type}{r.note ? ` · “${r.note}”` : ""}</small></span>
      {actions ? (
        <span className="request-actions">
          <button className="secondary-button approve" data-testid={`leave-req-approve-${r.id}`} onClick={() => decide(r, "approve")}><Check size={13} /> Onayla</button>
          <button className="secondary-button reject" data-testid={`leave-req-reject-${r.id}`} onClick={() => decide(r, "reject")}><X size={13} /> Reddet</button>
        </span>
      ) : <em className={`req-status ${r.status === "Onaylandı" ? "approved" : "rejected"}`}>{r.status}</em>}
    </div>
  );
  return (
    <section className="panel leave-requests" data-testid="leave-requests">
      <div className="panel-head"><div><h3>İzin talepleri {pending.length > 0 && <em className="count-badge" data-testid="leave-req-pending-count">{pending.length}</em>}</h3><span className="muted">Personelin kendi linkinden gönderdiği talepler · onaylanan günler takvime izin olarak eklenir</span></div><Inbox size={20} className="panel-icon" /></div>
      {!pending.length && <div className="empty-state small">Bekleyen talep yok.</div>}
      {pending.map((r, i) => <Row key={r.id} r={r} i={i} actions />)}
      {decided.length > 0 && <><small className="muted request-sub">Son kararlar</small>{decided.map((r, i) => <Row key={r.id} r={r} i={i} />)}</>}
    </section>
  );
};
