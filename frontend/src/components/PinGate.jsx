import { useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { LockKeyhole } from "lucide-react";
import { RESTAURANTS, errorText, session } from "@/lib/restaurant";
import { imageUrl } from "@/components/RestaurantImages";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

function ForgotPin({ restaurant, onDone }) {
  const [pin, setPin] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const send = async (e) => {
    e.preventDefault();
    if (!/^\d{4,6}$/.test(pin)) return toast.error("Şifre 4-6 haneli rakam olmalı");
    if (pin !== again) return toast.error("Şifreler aynı değil");
    setBusy(true);
    try { await axios.post(`${API}/restaurants/pin-request`, { restaurant_id: restaurant.id, new_pin: pin }); toast.success("Talebiniz yöneticiye gönderildi. Onaylanınca yeni şifrenizle girebilirsiniz"); onDone(); }
    catch (err) { toast.error(errorText(err, "Talep gönderilemedi")); }
    finally { setBusy(false); }
  };
  const clean = (fn) => (e) => fn(e.target.value.replace(/\D/g, ""));
  return (
    <form className="pin-gate panel" onSubmit={send} data-testid="forgot-pin-form">
      <h2>Yeni şifre iste</h2>
      <p className="muted">{restaurant.name} için istediğiniz yeni şifreyi yazın. Yönetici onaylayınca geçerli olur.</p>
      <label className="pin-field"><span>Yeni şifre</span><input type="password" inputMode="numeric" maxLength={6} value={pin} onChange={clean(setPin)} data-testid="forgot-pin-new" /></label>
      <label className="pin-field"><span>Yeni şifre (tekrar)</span><input type="password" inputMode="numeric" maxLength={6} value={again} onChange={clean(setAgain)} data-testid="forgot-pin-again" /></label>
      <button className="primary-button" disabled={busy} data-testid="forgot-pin-send">{busy ? "Gönderiliyor…" : "Talep gönder"}</button>
      <button type="button" className="text-button" onClick={onDone} data-testid="forgot-pin-back">Geri dön</button>
    </form>
  );
}

export const PinGate = ({ rid, onUnlocked }) => {
  const [forgot, setForgot] = useState(false);
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
  const one = targets.length === 1 ? targets[0] : null;
  if (forgot && one) return <ForgotPin restaurant={one} onDone={() => setForgot(false)} />;
  return (
    <form className={`pin-gate panel ${one?.cover_id ? "with-cover" : ""}`} onSubmit={submit} data-testid="pin-gate">
      {one?.cover_id && <img className="pin-cover" src={imageUrl(one.cover_id)} alt="" />}
      {one?.logo_id ? <img className="pin-logo" src={imageUrl(one.logo_id)} alt={`${one.name} logosu`} data-testid="pin-logo" /> : <div className="pin-icon"><LockKeyhole size={24} /></div>}
      <h2>{rid === "all" ? "Tüm restoranlar kilitli" : `${targets[0]?.name || ""} kilitli`}</h2>
      <p className="muted">Devam etmek için restoran şifresini girin.</p>
      {targets.map((r, i) => (
        <label key={r.id} className="pin-field">
          {targets.length > 1 && <span>{r.name}</span>}
          <input type="password" inputMode="numeric" autoComplete="off" maxLength={6} autoFocus={i === 0} value={pins[r.id] || ""} placeholder="••••" onChange={(e) => setPins({ ...pins, [r.id]: e.target.value.replace(/\D/g, "") })} data-testid={`pin-input-${r.id}`} />
        </label>
      ))}
      <button className="primary-button" disabled={busy} data-testid="pin-submit">{busy ? "Kontrol ediliyor…" : "Kilidi aç"}</button>
      {one && session.role !== "admin" && <button type="button" className="text-button" onClick={() => setForgot(true)} data-testid="forgot-pin-link">Şifremi unuttum</button>}
    </form>
  );
};
