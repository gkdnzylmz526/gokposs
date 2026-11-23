export const waPhone = (phone) => {
  const d = (phone || "").replace(/\D/g, "");
  if (!d) return "";
  if (d.startsWith("90")) return d;
  if (d.startsWith("0")) return `9${d}`;
  return d.length === 10 ? `90${d}` : d;
};

export const waLink = (phone, text) => `https://wa.me/${waPhone(phone)}?text=${encodeURIComponent(text)}`;
