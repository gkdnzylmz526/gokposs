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
  const sendNow = async (kind) => {
    setSending(kind);
    try { const { data } = await axios.post(`${API}/email/send-now`, null, { params: { kind } }); if (data.status === "sent") toast.success(`Rapor ${data.recipient} adresine gönderildi`); else toast.error(data.detail); }
    catch (e) { toast.error(e.response?.data?.detail || "E-posta gönderilemedi"); }
    finally { setSending(false); load(); }
  };
  const last = status?.history?.[0];
  return (
    <section className="panel email-card" data-testid="email-card">
      <div className="panel-head">
        <div><h3>Otomatik e-postalar</h3><span className="muted">Gün sonu: {status?.schedule || "Her gece 23:59"} · Haftalık özet: {status?.weekly_schedule || "Her pazartesi 09:00"} · Aylık özet: {status?.monthly_schedule || "Her ayın 1'i 09:00"} · {status?.recipient || "—"}</span></div>
        <Mail size={20} className="panel-icon" />
      </div>
      <div className="email-row">
        <div data-testid="email-last-status">
          {!status?.configured && <b className="danger-text">Gmail bilgileri henüz eklenmedi</b>}
          {status?.configured && !last && <b>Henüz gönderim yok</b>}
          {status?.configured && last && <b className={last.status === "sent" ? "green-text" : "danger-text"}>Son gönderim: {last.status === "sent" ? "Başarılı" : "Başarısız"}</b>}
          {last && <small>{new Date(last.created_at).toLocaleString("tr-TR", { dateStyle: "short", timeStyle: "short" })} · {{ weekly: "Haftalık özet", monthly: "Aylık özet", leave_request: "İzin talebi bildirimi" }[last.kind] || "Gün sonu"} · {last.trigger === "cron" ? "Otomatik" : "Manuel"}</small>}
        </div>
        <div className="email-buttons"><button className="secondary-button" data-testid="email-send-now-button" disabled={!!sending} onClick={() => sendNow("daily")}><Send size={15} /> {sending === "daily" ? "Gönderiliyor…" : "Gün sonunu gönder"}</button><button className="secondary-button" data-testid="email-send-monthly-button" disabled={!!sending} onClick={() => sendNow("monthly")}><Send size={15} /> {sending === "monthly" ? "Gönderiliyor…" : "Aylık özeti gönder"}</button><button className="secondary-button" data-testid="email-send-weekly-button" disabled={!!sending} onClick={() => sendNow("weekly")}><Send size={15} /> {sending === "weekly" ? "Gönderiliyor…" : "Haftalık özeti gönder"}</button></div>
      </div>
    </section>
  );
};
