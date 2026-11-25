import { useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { LockKeyhole } from "lucide-react";
import { RESTAURANTS, errorText } from "@/lib/restaurant";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export const PinGate = ({ rid, onUnlocked }) => {
  const targets = RESTAURANTS.filter((r) => r.has_pin && (rid === "all" || r.id === rid));
  const [pins, setPins] = useState({});
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    if (targets.some((r) => !pins[r.id])) return toast.error("Şifreyi girin");
    setBusy(true);
    try { const { data } = await axios.post(`${API}/restaurants/unlock`, { pins }); onUnlocked(data.token); }
    catch (err) { toast.error(errorText(err, "Şifre doğrulanamadı")); setPins({}); }
    finally { setBusy(false); }
  };
  return (
    <form className="pin-gate panel" onSubmit={submit} data-testid="pin-gate">
      <div className="pin-icon"><LockKeyhole size={24} /></div>
      <h2>{rid === "all" ? "Tüm restoranlar kilitli" : `${targets[0]?.name || ""} kilitli`}</h2>
      <p className="muted">Devam etmek için restoran şifresini girin.</p>
      {targets.map((r, i) => (
        <label key={r.id} className="pin-field">
          {targets.length > 1 && <span>{r.name}</span>}
          <input type="password" inputMode="numeric" autoComplete="off" maxLength={6} autoFocus={i === 0} value={pins[r.id] || ""} placeholder="••••" onChange={(e) => setPins({ ...pins, [r.id]: e.target.value.replace(/\D/g, "") })} data-testid={`pin-input-${r.id}`} />
        </label>
      ))}
      <button className="primary-button" disabled={busy} data-testid="pin-submit">{busy ? "Kontrol ediliyor…" : "Kilidi aç"}</button>
    </form>
  );
};
