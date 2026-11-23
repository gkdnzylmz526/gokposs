import { useEffect, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { useUser } from "@clerk/react";
import { AuditLog } from "@/components/AuditLog";
import { RESTAURANTS, errorText } from "@/lib/restaurant";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const roleLabel = { admin: "Yönetici (her şey)", staff: "Personel (masa, satış, stok, giriş-çıkış)", member: "Erişimi yok" };
const grid = { gridTemplateColumns: "1.8fr .8fr 1.2fr 1.2fr 1.2fr" };

export const UsersView = () => {
  const { user } = useUser();
  const [data, setData] = useState({ roles: [], users: [] });
  const [staff, setStaff] = useState([]);
  const load = () => axios.get(`${API}/users`).then(({ data: d }) => setData(d)).catch(() => toast.error("Kullanıcılar yüklenemedi"));
  useEffect(() => { load(); axios.get(`${API}/staff`, { headers: { "X-Restaurant": "all" } }).then(({ data: d }) => setStaff(d)).catch(() => setStaff([])); }, []);
  const change = async (u, role) => {
    try { await axios.patch(`${API}/users/${u.user_id}/role`, { role }); toast.success("Yetki güncellendi"); load(); }
    catch (e) { toast.error(errorText(e, "Yetki değiştirilemedi")); }
  };
  const assign = async (u, patch) => {
    const body = { restaurant_id: u.restaurant_id || RESTAURANTS[0].id, staff_id: u.staff_id || "", ...patch };
    if (patch.restaurant_id && patch.restaurant_id !== u.restaurant_id) body.staff_id = "";
    try { await axios.patch(`${API}/users/${u.user_id}/assignment`, body); toast.success("Atama güncellendi"); load(); }
    catch (e) { toast.error(errorText(e, "Atama yapılamadı")); }
  };
  return (
    <>
      <div className="welcome-row"><div><p className="eyebrow">AYARLAR</p><h2>Kullanıcılar</h2><p className="muted">Panele yalnızca "Yönetici" yetkisi olanlar girebilir. "Personel" yetkisi yalnızca bağlı olduğu restoranın masalarını, satış girişini, stok sayımını ve kendi giriş-çıkışını görür. Giriş-çıkış için personel hesabını bir personel kaydına bağlayın.</p></div></div>
      <section className="panel table-panel" data-testid="users-panel">
        <div className="spending-scroll">
          <div className="table-head" style={grid}><span>E-posta</span><span>Kayıt</span><span>Yetki</span><span>Restoran</span><span>Personel kaydı</span></div>
          {data.users.map((u, i) => {
            const rid = u.restaurant_id || RESTAURANTS[0].id;
            return (
              <div className="table-row" style={grid} key={u.user_id} data-testid={`user-row-${i}`}>
                <span>{u.email || u.user_id}{u.user_id === user?.id && <em className="recipe-badge">siz</em>}</span>
                <span>{u.created_at ? new Date(u.created_at).toLocaleDateString("tr-TR") : "—"}</span>
                <span><select value={u.role} data-testid={`user-role-${i}`} onChange={(e) => change(u, e.target.value)} className="role-select">{data.roles.map((r) => <option key={r} value={r}>{roleLabel[r] || r}</option>)}</select></span>
                <span>{u.role === "staff" ? <select value={rid} data-testid={`user-restaurant-${i}`} onChange={(e) => assign(u, { restaurant_id: e.target.value })} className="role-select">{RESTAURANTS.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}</select> : <small className="muted">Tümü</small>}</span>
                <span>{u.role === "staff" ? <select value={u.staff_id || ""} data-testid={`user-staff-${i}`} onChange={(e) => assign(u, { staff_id: e.target.value })} className="role-select"><option value="">Bağlı değil</option>{staff.filter((s) => s.restaurant_id === rid).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select> : <small className="muted">—</small>}</span>
              </div>
            );
          })}
        </div>
      </section>
      <AuditLog />
    </>
  );
};
