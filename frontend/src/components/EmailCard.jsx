import { useEffect, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Mail, Send } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export const EmailCard = () => {
  const [status, setStatus] = useState(null);
  const [sending, setSending] = useState(false);
  const load = () => axios.get(`${API}/email/status`).then(({ data }) => setStatus(data)).catch(() => {});
  useEffect(() => { load(); }, []);
  const sendNow = async () => {
    setSending(true);
    try { const { data } = await axios.post(`${API}/email/send-now`); toast.success(`Rapor ${data.recipient} adresine gönderildi`); }
    catch (e) { toast.error(e.response?.data?.detail || "E-posta gönderilemedi"); }
    finally { setSending(false); load(); }
  };
  const last = status?.history?.[0];
  return (
    <section className="panel email-card" data-testid="email-card">
      <div className="panel-head">
        <div><h3>Gün sonu e-postası</h3><span className="muted">{status?.schedule || "Her gece 23:59"} · {status?.recipient || "—"}</span></div>
        <Mail size={20} className="panel-icon" />
      </div>
      <div className="email-row">
        <div data-testid="email-last-status">
          {!status?.configured && <b className="danger-text">Gmail bilgileri henüz eklenmedi</b>}
          {status?.configured && !last && <b>Henüz gönderim yok</b>}
          {status?.configured && last && <b className={last.status === "sent" ? "green-text" : "danger-text"}>Son gönderim: {last.status === "sent" ? "Başarılı" : "Başarısız"}</b>}
          {last && <small>{new Date(last.created_at).toLocaleString("tr-TR", { dateStyle: "short", timeStyle: "short" })} · {last.trigger === "cron" ? "Otomatik" : "Manuel"}</small>}
        </div>
        <button className="secondary-button" data-testid="email-send-now-button" disabled={sending} onClick={sendNow}><Send size={15} /> {sending ? "Gönderiliyor…" : "Şimdi gönder"}</button>
      </div>
    </section>
  );
};
