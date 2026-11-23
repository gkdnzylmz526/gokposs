import { useMemo, useState } from "react";
import { addDays, format, parseISO, startOfWeek } from "date-fns";
import { tr } from "date-fns/locale";
import { ChevronLeft, ChevronRight, Plus, X } from "lucide-react";

const hours = (s) => { const [sh, sm] = s.start.split(":").map(Number); const [eh, em] = s.end.split(":").map(Number); let d = eh * 60 + em - (sh * 60 + sm); if (d < 0) d += 1440; return d / 60; };

export const ShiftCalendar = ({ staff, shifts, onAdd, onEdit, onDelete }) => {
  const [weekStart, setWeekStart] = useState(() => startOfWeek(new Date(), { weekStartsOn: 1 }));
  const days = useMemo(() => Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)), [weekStart]);
  const today = format(new Date(), "yyyy-MM-dd");
  const byCell = useMemo(() => shifts.reduce((all, s) => ({ ...all, [`${s.staff_id}|${s.date}`]: [...(all[`${s.staff_id}|${s.date}`] || []), s] }), {}), [shifts]);
  const defaultHours = (person) => { const m = (person.shift || "").match(/(\d{1,2}:\d{2}).*?(\d{1,2}:\d{2})/); return m ? { start: m[1].padStart(5, "0"), end: m[2].padStart(5, "0") } : { start: "09:00", end: "17:00" }; };
  return (
    <section className="panel shift-calendar" data-testid="shift-calendar">
      <div className="panel-head">
        <div><h3>Haftalık vardiya takvimi</h3><span className="muted">{format(days[0], "d MMMM", { locale: tr })} – {format(days[6], "d MMMM yyyy", { locale: tr })}</span></div>
        <div className="week-nav">
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
              const total = days.reduce((sum, d) => sum + (byCell[`${person.id}|${format(d, "yyyy-MM-dd")}`] || []).reduce((t, s) => t + hours(s), 0), 0);
              return [
                <div key={person.id} className="shift-person" data-testid={`shift-person-${person.id}`}><b>{person.name}</b><small>{person.task || "—"} · {Number(total.toFixed(1)).toLocaleString("tr-TR")} saat</small></div>,
                ...days.map((d) => {
                  const date = format(d, "yyyy-MM-dd");
                  const cell = byCell[`${person.id}|${date}`] || [];
                  return (
                    <div key={`${person.id}-${date}`} className={`shift-cell ${date === today ? "today" : ""}`} data-testid={`shift-cell-${person.id}-${date}`}>
                      {cell.map((s) => (
                        <div key={s.id} className="shift-chip" data-testid={`shift-chip-${s.id}`} onClick={() => onEdit("shifts", s)}>
                          <span>{s.start}–{s.end}</span>{s.task && <small>{s.task}</small>}
                          <button className="chip-x" title="Sil" data-testid={`shift-delete-${s.id}`} onClick={(e) => { e.stopPropagation(); onDelete("shifts", s.id); }}><X size={11} /></button>
                        </div>
                      ))}
                      <button className="shift-add" title="Vardiya ekle" data-testid={`shift-add-${person.id}-${date}`} onClick={() => onAdd("shifts", { staff_id: person.id, date, ...defaultHours(person), task: person.task || "" })}><Plus size={13} /></button>
                    </div>
                  );
                }),
              ];
            })}
          </div>
        </div>
      )}
    </section>
  );
};

export const shiftTitle = (item, staff) => `${staff.find((p) => p.id === item?.staff_id)?.name || "Vardiya"} · ${item?.date ? format(parseISO(item.date), "d MMMM EEEE", { locale: tr }) : ""}`;
