import { useEffect, useState } from "react";
import axios from "axios";
import { SignOutButton, useAuth, useUser } from "@clerk/react";
import { ShieldAlert } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// Attaches the Clerk session token to every axios call, then lets only admins into the dashboard.
export const AuthGate = ({ children }) => {
  const { getToken } = useAuth();
  const { user } = useUser();
  const [me, setMe] = useState(null);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const id = axios.interceptors.request.use(async (config) => {
      const token = await getToken();
      if (token) config.headers.Authorization = `Bearer ${token}`;
      return config;
    });
    setReady(true);
    axios.get(`${API}/me`).then(({ data }) => setMe(data)).catch((e) => setMe({ role: e.response?.status === 403 ? "member" : "error" }));
    return () => axios.interceptors.request.eject(id);
  }, [getToken]);
  if (!ready || !me) return <div className="auth-loading" data-testid="auth-loading">Yükleniyor…</div>;
  if (me.role === "admin") return children;
  if (me.role === "error") return <div className="auth-loading" data-testid="auth-error"><div style={{ textAlign: "center" }}><p>Bağlantı kurulamadı. Lütfen tekrar deneyin.</p><button className="primary-button" data-testid="auth-retry" onClick={() => window.location.reload()}>Tekrar dene</button></div></div>;
  return (
    <div className="public-page" data-testid="access-denied">
      <div className="public-card">
        <div className="brand public-brand"><div className="brand-mark">G</div><div><strong>GÖKBOSS POS</strong><span>Yönetim paneli</span></div></div>
        <div className="denied-icon"><ShieldAlert size={26} /></div>
        <h1>Erişim yetkiniz yok</h1>
        <p className="muted">{user?.primaryEmailAddress?.emailAddress} hesabı bu panele yönetici olarak tanımlı değil. Restoran yöneticisinden size yetki vermesini isteyin.</p>
        <SignOutButton><button className="primary-button full" data-testid="access-denied-signout">Çıkış yap</button></SignOutButton>
      </div>
    </div>
  );
};
