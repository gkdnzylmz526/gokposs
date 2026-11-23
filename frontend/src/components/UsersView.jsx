import { useEffect, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { useUser } from "@clerk/react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const roleLabel = { admin: "Yönetici", member: "Erişimi yok" };

export const UsersView = () => {
  const { user } = useUser();
  const [data, setData] = useState({ roles: [], users: [] });
  const load = () => axios.get(`${API}/users`).then(({ data: d }) => setData(d)).catch(() => toast.error("Kullanıcılar yüklenemedi"));
  useEffect(() => { load(); }, []);
  const change = async (u, role) => {
    try { await axios.patch(`${API}/users/${u.user_id}/role`, { role }); toast.success("Yetki güncellendi"); load(); }
    catch (e) { toast.error(e.response?.data?.detail || "Yetki değiştirilemedi"); }
  };
  return (
    <>
      <div className="welcome-row"><div><p className="eyebrow">AYARLAR</p><h2>Kullanıcılar</h2><p className="muted">Panele yalnızca "Yönetici" yetkisi olanlar girebilir. Yeni biri kayıt olduğunda "Erişimi yok" olarak başlar; buradan yönetici yapabilirsiniz.</p></div></div>
      <section className="panel table-panel" data-testid="users-panel">
        <div className="table-head" style={{ gridTemplateColumns: "2fr 1fr 1fr" }}><span>E-posta</span><span>Kayıt</span><span>Yetki</span></div>
        {data.users.map((u, i) => (
          <div className="table-row" style={{ gridTemplateColumns: "2fr 1fr 1fr" }} key={u.user_id} data-testid={`user-row-${i}`}>
            <span>{u.email || u.user_id}{u.user_id === user?.id && <em className="recipe-badge">siz</em>}</span>
            <span>{u.created_at ? new Date(u.created_at).toLocaleDateString("tr-TR") : "—"}</span>
            <span><select value={u.role} data-testid={`user-role-${i}`} onChange={(e) => change(u, e.target.value)} className="role-select">{data.roles.map((r) => <option key={r} value={r}>{roleLabel[r] || r}</option>)}</select></span>
          </div>
        ))}
      </section>
    </>
  );
};
