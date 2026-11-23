import { useCallback, useEffect, useRef, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { ChefHat, Volume2, VolumeX } from "lucide-react";
import { errorText } from "@/lib/restaurant";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const COLUMNS = [["Yeni", "Yeni sipariş", "Hazırlanıyor", "Hazırlamaya başla"], ["Hazırlanıyor", "Hazırlanıyor", "Hazır", "Hazır"], ["Hazır", "Servise hazır", "Teslim edildi", "Teslim edildi"]];
const elapsed = (iso) => Math.max(0, Math.round((Date.now() - new Date(iso)) / 60000));
const beep = () => { try { const ctx = new (window.AudioContext || window.webkitAudioContext)(); const o = ctx.createOscillator(); const g = ctx.createGain(); o.connect(g); g.connect(ctx.destination); o.frequency.value = 880; g.gain.value = 0.15; o.start(); o.stop(ctx.currentTime + 0.25); } catch { /* sound unsupported */ } };

function Ticket({ t, next, label, onMove }) {
  const mins = elapsed(t.created_at);
  return (
    <article className={`kitchen-ticket ${mins >= 20 && t.status !== "Hazır" ? "late" : ""}`} data-testid={`kitchen-ticket-${t.id}`}>
      <header><b>Masa {t.table_name}</b><span data-testid={`kitchen-ticket-time-${t.id}`}>{mins} dk</span></header>
      <ul>{t.items.map((i) => <li key={i.product_id}><em>{Number(i.quantity).toLocaleString("tr-TR")}×</em>{i.product_name}</li>)}</ul>
      <button className={next === "Teslim edildi" ? "secondary-button full" : "primary-button full"} data-testid={`kitchen-move-${t.id}`} onClick={() => onMove(t, next)}>{label}</button>
    </article>
  );
}

export const KitchenBoard = () => {
  const [tickets, setTickets] = useState([]);
  const [sound, setSound] = useState(true);
  const known = useRef(null);
  const load = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API}/kitchen`);
      const fresh = data.filter((t) => t.status === "Yeni" && known.current && !known.current.has(t.id));
      if (fresh.length && sound) beep();
      known.current = new Set(data.map((t) => t.id));
      setTickets(data);
    } catch (e) { toast.error(errorText(e, "Mutfak siparişleri yüklenemedi")); }
  }, [sound]);
  useEffect(() => { load(); const id = setInterval(load, 8000); return () => clearInterval(id); }, [load]);
  const move = async (t, status) => { try { await axios.post(`${API}/kitchen/${t.id}/status`, { status }); load(); } catch (e) { toast.error(errorText(e, "Güncellenemedi")); } };
  return (
    <div className="kitchen-board" data-testid="kitchen-board">
      <div className="tables-head"><span className="muted"><ChefHat size={14} /> Masalara eklenen ürünler buraya düşer · 8 saniyede bir yenilenir</span><button className="secondary-button" data-testid="kitchen-sound-toggle" onClick={() => setSound(!sound)}>{sound ? <><Volume2 size={14} /> Ses açık</> : <><VolumeX size={14} /> Ses kapalı</>}</button></div>
      <div className="kitchen-columns">
        {COLUMNS.map(([status, title, next, label]) => {
          const list = tickets.filter((t) => t.status === status);
          return (
            <section key={status} className={`kitchen-col col-${status === "Yeni" ? "new" : status === "Hazır" ? "ready" : "cooking"}`} data-testid={`kitchen-col-${status}`}>
              <h3>{title}<span>{list.length}</span></h3>
              {!list.length && <div className="empty-state">Boş</div>}
              {list.map((t) => <Ticket key={t.id} t={t} next={next} label={label} onMove={move} />)}
            </section>
          );
        })}
      </div>
    </div>
  );
};

export const KitchenView = () => (
  <>
    <div className="welcome-row"><div><p className="eyebrow">MUTFAK</p><h2>Mutfak Ekranı</h2><p className="muted">Garsonun masaya eklediği ürünler anında gelir. Hazır olanı işaretleyin; garson masada "hazır" uyarısını görür.</p></div></div>
    <KitchenBoard />
  </>
);
