import { useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Sparkles } from "lucide-react";
import { errorText } from "@/lib/restaurant";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export const AiWeeklyCard = () => {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try { const { data: d } = await axios.get(`${API}/ai/weekly-preview`); setData(d); }
    catch (e) { toast.error(errorText(e, "Yorum oluşturulamadı")); } finally { setBusy(false); }
  };
  return (
    <section className="panel ai-weekly" data-testid="ai-weekly-card">
      <div className="panel-head">
        <div><h3><Sparkles size={16} /> Haftalık yapay zeka yorumu</h3><span className="muted">Her pazartesi 09:00'da haftalık özet e-postanıza eklenir. İsterseniz şimdi görün.</span></div>
        <button className="primary-button" disabled={busy} onClick={run} data-testid="ai-weekly-generate">{busy ? "Hazırlanıyor…" : data ? "Yenile" : "Geçen haftayı yorumla"}</button>
      </div>
      {data && <div className="ai-weekly-text" data-testid="ai-weekly-text"><small className="muted">{data.week}</small><p>{data.text}</p></div>}
    </section>
  );
};
