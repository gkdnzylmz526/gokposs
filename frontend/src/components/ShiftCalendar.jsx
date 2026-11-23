import { useMemo, useState } from "react";
import { addDays, format, parseISO, startOfWeek } from "date-fns";
import { tr } from "date-fns/locale";
import { CalendarOff, ChevronLeft, ChevronRight, Copy, MessageCircle, Plus, Send, X } from "lucide-react";
import { BulkPlanDialog } from "@/components/BulkPlanDialog";
import { waLink } from "@/lib/phone";
import axios from "axios";
import { toast } from "sonner";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const money = (n) => new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY", maximumFractionDigits: 2 }).format(n || 0);

const hours = (s) => { const [sh, sm] = s.start.split(":").map(Number); const [eh, em] = s.end.split(":").map(Number); let d = eh * 60 + em - (sh * 60 + sm); if (d < 0) d += 1440; return d / 60; };

export const ShiftCalendar = ({ staff, shifts, leaves = [], onAdd, onEdit, onDelete, onReload }) => {
  const [bulkOpen, setBulkOpen] = useState(false);
  const [copying, setCopying] = useState(false);
  const [weekStart, setWeekStart] = useState(() => startOfWeek(new Date(), { weekStartsOn: 1 }));
  const days = useMemo(() => Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)), [weekStart]);
  const today = format(new Date(), "yyyy-MM-dd");
  const byCell = useMemo(() => shifts.reduce((all, s) => ({ ...all, [`${s.staff_id}|${s.date}`]: [...(all[`${s.staff_id}|${s.date}`] || []), s] }), {}), [shifts]);
  const leaveByCell = useMemo(() => Object.fromEntries(leaves.map((l) => [`${l.staff_id}|${l.date}`, l])), [leaves]);
  const year = String(new Date().getFullYear());
  const leaveBalance = (p) => { const used = leaves.filter((l) => l.staff_id === p.id && l.type === "Yıllık izin" && l.date.startsWith(year)).length; const total = Number(p.annual_leave_days ?? 14); return { used, total, remaining: total - used }; };
  const weekLabel = `${format(days[0], "d MMMM", { locale: tr })} – ${format(days[6], "d MMMM yyyy", { locale: tr })}`;
  const weekHours = (person) => days.reduce((sum, d) => sum + (byCell[`${person.id}|${format(d, "yyyy-MM-dd")}`] || []).reduce((t, s) => t + hours(s), 0), 0);
  const weekPay = (p) => { const h = weekHours(p), w = Number(p.hourly_wage || 0), ot = Math.max(0, h - 45); return { hours: h, overtime: ot, pay: (h - ot) * w + ot * w * 1.5 }; };
  const payroll = staff.reduce((sum, p) => sum + weekPay(p).pay, 0);
  const planText = (person) => [`Merhaba ${person.name}, ${format(days[0], "d MMMM", { locale: tr })} – ${format(days[6], "d MMMM", { locale: tr })} vardiya planın:`, ...days.map((d) => { const list = byCell[`${person.id}|${format(d, "yyyy-MM-dd")}`] || []; const leave = leaveByCell[`${person.id}|${format(d, "yyyy-MM-dd")}`]; return `${format(d, "EEEE dd.MM", { locale: tr })}: ${list.length ? list.map((s) => `${s.start}–${s.end}${s.task ? ` (${s.task})` : ""}`).join(", ") : leave ? leave.type : "Boş gün"}`; }), `Toplam: ${Number(weekHours(person).toFixed(1)).toLocaleString("tr-TR")} saat`, "GÖKBOSS POS"].join("\n");
  const totalHours = staff.reduce((sum, p) => sum + weekHours(p), 0);
  const copyLastWeek = async () => {
    const from = format(addDays(weekStart, -7), "yyyy-MM-dd"), to = format(weekStart, "yyyy-MM-dd");
    if (!window.confirm("Önceki haftanın vardiyaları bu haftaya kopyalansın mı? Aynı gün ve saatteki vardiyalar tekrar eklenmez.")) return;
    setCopying(true);
    try { const { data } = await axios.post(`${API}/shifts/copy-week`, { from_start: from, to_start: to }); await onReload(); toast[data.created ? "success" : "info"](!data.source_count ? "Önceki haftada vardiya yok" : data.created ? `${data.created} vardiya kopyalandı` : "Tüm vardiyalar zaten mevcut"); } catch { toast.error("Vardiyalar kopyalanamadı"); } finally { setCopying(false); }
  };
  const defaultHours = (person) => { const m = (person.shift || "").match(/(\d{1,2}:\d{2}).*?(\d{1,2}:\d{2})/); return m ? { start: m[1].padStart(5, "0"), end: m[2].padStart(5, "0") } : { start: "09:00", end: "17:00" }; };
  return (
    <section className="panel shift-calendar" data-testid="shift-calendar">
      <div className="panel-head">
        <div><h3>Haftalık vardiya takvimi</h3><span className="muted">{weekLabel}</span></div>
        <div className="week-nav">
          <button className="secondary-button" data-testid="shift-bulk-send" onClick={() => setBulkOpen(true)} disabled={!staff.length}><Send size={13} /> Planı herkese gönder</button>
          <button className="secondary-button" data-testid="shift-copy-week" disabled={copying} onClick={copyLastWeek}><Copy size={13} /> {copying ? "Kopyalanıyor…" : "Önceki haftayı kopyala"}</button>
          <button className="icon-button" data-testid="shift-prev-week" onClick={() => setWeekStart(addDays(weekStart, -7))}><ChevronLeft size={16} /></button>
          <button className="secondary-button" data-testid="shift-this-week" onClick={() => setWeekStart(startOfWeek(new Date(), { weekStartsOn: 1 }))}>Bu hafta</button>
          <button className="icon-button" data-testid="shift-next-week" onClick={() => setWeekStart(addDays(weekStart, 7))}><ChevronRight size={16} /></button>
        </div>
      </div>
      {!staff.length ? <div className="empty-state">Takvimi kullanmak için önce personel ekleyin.</div> : (
        <div className="shift-scroll">
          <div className="shift-grid">
            <div className="shift-corner">Personel</div>
            {days.map((d) => { const key = format(d, "yyyy-MM-dd"); return <div key={key} className={`shift-day ${key === today ? "today" : ""}`}>{format(d, "EEE", { locale: tr })}<b>{format(d, "dd.MM")}</b></div>; })}
            {staff.map((person) => {
              const total = weekHours(person);
              return [
                <div key={person.id} className="shift-person" data-testid={`shift-person-${person.id}`}><b>{person.name}</b><small>{person.task || "—"} · {Number(total.toFixed(1)).toLocaleString("tr-TR")} saat</small><small className="pay" data-testid={`shift-pay-${person.id}`}>{person.hourly_wage ? `${money(weekPay(person).pay)} (${money(person.hourly_wage)}/saat)` : "Saatlik ücret girilmemiş"}</small>{weekPay(person).overtime > 0 && <small className="ot-text" data-testid={`shift-overtime-${person.id}`}>Fazla mesai: {Number(weekPay(person).overtime.toFixed(1)).toLocaleString("tr-TR")} saat{person.hourly_wage ? ` · ${money(weekPay(person).overtime * person.hourly_wage * 1.5)}` : ""}</small>}<small className="leave-balance" data-testid={`leave-balance-${person.id}`}>Yıllık izin: {leaveBalance(person).remaining} / {leaveBalance(person).total} gün kaldı</small><a className={`wa-mini ${person.phone ? "" : "disabled"}`} data-testid={`shift-whatsapp-${person.id}`} href={person.phone ? waLink(person.phone, planText(person)) : undefined} target="_blank" rel="noreferrer" title={person.phone ? "Haftalık planı WhatsApp'ta gönder" : "Telefon numarası girilmemiş"}><MessageCircle size={12} /> {person.phone ? "Planı gönder" : "Telefon yok"}</a></div>,
                ...days.map((d) => {
                  const date = format(d, "yyyy-MM-dd");
                  const cell = byCell[`${person.id}|${date}`] || [];
                  const leave = leaveByCell[`${person.id}|${date}`];
                  return (
                    <div key={`${person.id}-${date}`} className={`shift-cell ${date === today ? "today" : ""} ${leave ? "on-leave" : ""}`} data-testid={`shift-cell-${person.id}-${date}`}>
                      {leave && <div className="leave-chip" data-testid={`leave-chip-${leave.id}`} onClick={() => onEdit("leaves", leave)}><CalendarOff size={11} /> {leave.type}<button className="chip-x" title="İzni sil" data-testid={`leave-delete-${leave.id}`} onClick={(e) => { e.stopPropagation(); if (window.confirm(`${leave.type} silinsin mi?`)) onDelete("leaves", leave.id); }}><X size={11} /></button></div>}
                      {cell.map((s) => (
                        <div key={s.id} className="shift-chip" data-testid={`shift-chip-${s.id}`} onClick={() => onEdit("shifts", s)}>
                          <span>{s.start}–{s.end}</span>{s.task && <small>{s.task}</small>}
                          <button className="chip-x" title="Sil" data-testid={`shift-delete-${s.id}`} onClick={(e) => { e.stopPropagation(); if (window.confirm(`${s.start}–${s.end} vardiyası silinsin mi?`)) onDelete("shifts", s.id); }}><X size={11} /></button>
                        </div>
                      ))}
                      <div className="cell-actions"><button className="shift-add" title="Vardiya ekle" data-testid={`shift-add-${person.id}-${date}`} onClick={() => onAdd("shifts", { staff_id: person.id, date, ...defaultHours(person), task: person.task || "" })}><Plus size={13} /></button>{!leave && <button className="shift-add leave-add" title="İzin ekle" data-testid={`leave-add-${person.id}-${date}`} onClick={() => onAdd("leaves", { staff_id: person.id, date, type: "Yıllık izin" })}><CalendarOff size={12} /></button>}</div>
                    </div>
                  );
                }),
              ];
            })}
          </div>
          <div className="payroll-bar" data-testid="shift-payroll"><span>Haftalık toplam: <b>{Number(totalHours.toFixed(1)).toLocaleString("tr-TR")} saat</b></span><span>Tahmini maaş gideri: <b data-testid="shift-payroll-total">{money(payroll)}</b></span></div>
        </div>
      )}
      {bulkOpen && <BulkPlanDialog staff={staff} planText={planText} weekLabel={weekLabel} onClose={() => setBulkOpen(false)} />}
    </section>
  );
};

export const shiftTitle = (item, staff) => `${staff.find((p) => p.id === item?.staff_id)?.name || "Vardiya"} · ${item?.date ? format(parseISO(item.date), "d MMMM EEEE", { locale: tr }) : ""}`;
