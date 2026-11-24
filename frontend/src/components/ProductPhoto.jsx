import { useRef, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Camera, ImagePlus, Trash2 } from "lucide-react";
import { errorText } from "@/lib/restaurant";

const BASE = process.env.REACT_APP_BACKEND_URL;
export const photoUrl = (product) => (product.photo?.id ? `${BASE}/api/public/photos/${product.photo.id}` : "");

const shrink = (file) => new Promise((resolve) => {
  const img = new Image();
  const url = URL.createObjectURL(file);
  img.onload = () => {
    const scale = Math.min(1, 1200 / Math.max(img.width, img.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(img.width * scale); canvas.height = Math.round(img.height * scale);
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#ffffff"; ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    URL.revokeObjectURL(url);
    canvas.toBlob((blob) => resolve(blob ? new File([blob], "urun.jpg", { type: "image/jpeg" }) : file), "image/jpeg", 0.85);
  };
  img.onerror = () => { URL.revokeObjectURL(url); resolve(null); };
  img.src = url;
});

export const ProductPhoto = ({ product, onChange }) => {
  const input = useRef(null);
  const [busy, setBusy] = useState(false);
  const upload = async (file) => {
    if (!file) return;
    setBusy(true);
    try {
      const small = await shrink(file);
      if (!small) throw new Error("decode");
      const form = new FormData(); form.append("file", small);
      await axios.post(`${BASE}/api/products/${product.id}/photo`, form);
      toast.success("Fotoğraf eklendi, QR menüde görünüyor"); onChange();
    } catch (e) { toast.error(e.message === "decode" ? "Bu fotoğraf açılamadı; JPG veya PNG deneyin" : errorText(e, "Fotoğraf yüklenemedi")); }
    finally { setBusy(false); if (input.current) input.current.value = ""; }
  };
  const remove = async () => { if (!window.confirm("Fotoğraf kaldırılsın mı?")) return; try { await axios.delete(`${BASE}/api/products/${product.id}/photo`); onChange(); } catch (e) { toast.error(errorText(e, "Kaldırılamadı")); } };
  const src = photoUrl(product);
  return (
    <div className={`product-photo ${src ? "has" : ""}`} data-testid={`product-photo-${product.id}`}>
      {src ? <img src={src} alt={product.name} loading="lazy" data-testid={`product-photo-img-${product.id}`} /> : <button className="photo-empty" disabled={busy} data-testid={`product-photo-add-${product.id}`} onClick={() => input.current?.click()}><ImagePlus size={20} /><span>{busy ? "Yükleniyor…" : "Fotoğraf ekle"}</span><small>QR menüde görünür</small></button>}
      {src && <div className="photo-actions"><button disabled={busy} data-testid={`product-photo-change-${product.id}`} onClick={() => input.current?.click()}><Camera size={13} /> {busy ? "Yükleniyor…" : "Değiştir"}</button><button data-testid={`product-photo-remove-${product.id}`} onClick={remove}><Trash2 size={13} /></button></div>}
      <input ref={input} type="file" hidden accept="image/*" data-testid={`product-photo-input-${product.id}`} onChange={(e) => upload(e.target.files?.[0])} />
    </div>
  );
};
