import { useRef, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { ImagePlus, Trash2 } from "lucide-react";
import { errorText } from "@/lib/restaurant";

const BASE = process.env.REACT_APP_BACKEND_URL;
export const imageUrl = (id) => (id ? `${BASE}/api/public/photos/${id}` : "");

const shrink = (file, max) => new Promise((resolve) => {
  const img = new Image();
  const url = URL.createObjectURL(file);
  img.onload = () => {
    const scale = Math.min(1, max / Math.max(img.width, img.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(img.width * scale); canvas.height = Math.round(img.height * scale);
    canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
    URL.revokeObjectURL(url);
    const png = file.type === "image/png";
    canvas.toBlob((blob) => resolve(blob ? new File([blob], png ? "gorsel.png" : "gorsel.jpg", { type: png ? "image/png" : "image/jpeg" }) : null), png ? "image/png" : "image/jpeg", 0.85);
  };
  img.onerror = () => { URL.revokeObjectURL(url); resolve(null); };
  img.src = url;
});

function ImageSlot({ item, kind, label, onChange }) {
  const input = useRef(null);
  const [busy, setBusy] = useState(false);
  const id = item[`${kind}_id`];
  const upload = async (file) => {
    if (!file) return;
    setBusy(true);
    try {
      const small = await shrink(file, kind === "logo" ? 600 : 1800);
      if (!small) throw new Error("decode");
      const form = new FormData(); form.append("file", small);
      await axios.post(`${BASE}/api/restaurants/manage/${item.id}/image/${kind}`, form);
      toast.success(`${label} yüklendi`); onChange();
    } catch (e) { toast.error(e.message === "decode" ? "Bu görsel açılamadı; JPG veya PNG deneyin" : errorText(e, "Yüklenemedi")); }
    finally { setBusy(false); if (input.current) input.current.value = ""; }
  };
  const remove = async () => { try { await axios.delete(`${BASE}/api/restaurants/manage/${item.id}/image/${kind}`); onChange(); } catch (e) { toast.error(errorText(e, "Kaldırılamadı")); } };
  return (
    <div className={`rest-image rest-image-${kind}`} data-testid={`restaurant-${kind}-slot`}>
      <span>{label}</span>
      <button type="button" className="rest-image-box" disabled={busy} onClick={() => input.current?.click()} data-testid={`restaurant-${kind}-upload`}>
        {id ? <img src={imageUrl(id)} alt={label} data-testid={`restaurant-${kind}-img`} /> : <><ImagePlus size={18} /> {busy ? "Yükleniyor…" : "Görsel seç"}</>}
      </button>
      {id && <button type="button" className="text-button danger-text" onClick={remove} data-testid={`restaurant-${kind}-remove`}><Trash2 size={13} /> Kaldır</button>}
      <input ref={input} type="file" hidden accept="image/*" data-testid={`restaurant-${kind}-input`} onChange={(e) => upload(e.target.files?.[0])} />
    </div>
  );
}

export const RestaurantImages = ({ item, onChange }) => (
  <div className="rest-images">
    <ImageSlot item={item} kind="logo" label="Logo" onChange={onChange} />
    <ImageSlot item={item} kind="cover" label="Kapak fotoğrafı" onChange={onChange} />
  </div>
);

export const RestaurantHero = ({ restaurant }) => {
  if (!restaurant || (!restaurant.cover_id && !restaurant.logo_id)) return null;
  return (
    <section className={`rest-hero ${restaurant.cover_id ? "" : "no-cover"}`} data-testid="restaurant-hero">
      {restaurant.cover_id && <img className="rest-hero-cover" src={imageUrl(restaurant.cover_id)} alt="" />}
      <div className="rest-hero-body">
        {restaurant.logo_id && <img className="rest-hero-logo" src={imageUrl(restaurant.logo_id)} alt={`${restaurant.name} logosu`} data-testid="restaurant-hero-logo" />}
        <h2 data-testid="restaurant-hero-name">{restaurant.name}</h2>
      </div>
    </section>
  );
};
