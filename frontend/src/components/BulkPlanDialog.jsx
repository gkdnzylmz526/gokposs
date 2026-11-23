import { useState } from "react";
import { Check, MessageCircle, Send, X } from "lucide-react";
import { waLink } from "@/lib/phone";

export const BulkPlanDialog = ({ staff, planText, weekLabel, onClose }) => {
  const reachable = staff.filter((p) => p.phone);
  const [sent, setSent] = useState(() => new Set());
  const open = (person) => { window.open(waLink(person.phone, planText(person)), "_blank", "noopener"); setSent((s) => new Set(s).add(person.id)); };
  const next = reachable.find((p) => !sent.has(p.id));
  return (
    <div className="modal-backdrop">
      <div className="modal bulk-modal" data-testid="bulk-plan-dialog">
        <button className="icon-button close" data-testid="bulk-plan-close" onClick={onClose}><X size={18} /></button>
        <span className="eyebrow">TOPLU PLAN GÖNDERİMİ</span>
        <h2>Haftalık planı ekibe gönder</h2>
        <p className="muted bulk-note">{weekLabel} · WhatsApp her mesaj için ayrı sohbet açar; "Sıradakini gönder" ile kişiden kişiye hızlıca geçin.</p>
        <div className="bulk-list">
          {staff.map((p) => (
            <div key={p.id} className={`bulk-row ${sent.has(p.id) ? "sent" : ""}`} data-testid={`bulk-plan-row-${p.id}`}>
              <span className="bulk-status">{sent.has(p.id) ? <Check size={14} /> : null}</span>
              <span><b>{p.name}</b><small>{p.phone || "Telefon numarası yok"}</small></span>
              {p.phone ? <button className="secondary-button" data-testid={`bulk-plan-send-${p.id}`} onClick={() => open(p)}><MessageCircle size={13} /> {sent.has(p.id) ? "Tekrar" : "Gönder"}</button> : <span className="muted">—</span>}
            </div>
          ))}
        </div>
        <button className="primary-button full" data-testid="bulk-plan-next" disabled={!next} onClick={() => next && open(next)}>
          <Send size={16} /> {next ? `Sıradakini gönder: ${next.name} (${sent.size}/${reachable.length})` : reachable.length ? "Herkese gönderildi" : "Telefonu olan personel yok"}
        </button>
      </div>
    </div>
  );
};
