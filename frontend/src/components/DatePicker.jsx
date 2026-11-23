import { useState } from "react";
import { format, parseISO } from "date-fns";
import { tr } from "date-fns/locale";
import { CalendarDays } from "lucide-react";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

export const DatePicker = ({ label, value, onChange, min, max, testId }) => {
  const [open, setOpen] = useState(false);
  const selected = value ? parseISO(value) : undefined;
  const disabled = [min && { before: parseISO(min) }, max && { after: parseISO(max) }].filter(Boolean);
  return (
    <label className="date-picker-field">{label}
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button type="button" className="date-picker-trigger" data-testid={testId}>
            <CalendarDays size={15} /> {selected ? format(selected, "dd.MM.yyyy") : "gg.aa.yyyy"}
          </button>
        </PopoverTrigger>
        <PopoverContent className="date-popover w-auto p-0" align="start" data-testid={`${testId}-calendar`}>
          <Calendar mode="single" locale={tr} weekStartsOn={1} selected={selected} defaultMonth={selected || (min ? parseISO(min) : undefined)} disabled={disabled}
            onSelect={(d) => { if (d) { onChange(format(d, "yyyy-MM-dd")); setOpen(false); } }} initialFocus />
        </PopoverContent>
      </Popover>
    </label>
  );
};
