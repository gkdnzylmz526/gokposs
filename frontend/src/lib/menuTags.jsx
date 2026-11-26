import { Flame, Leaf, Sprout, Nut, WheatOff, Milk } from "lucide-react";

export const MENU_TAGS = [
  { key: "spicy", icon: Flame, color: "#e4572e", label: { tr: "Acılı", en: "Spicy", ar: "حار", ru: "Острое" } },
  { key: "vegetarian", icon: Leaf, color: "#3a9e5c", label: { tr: "Vejetaryen", en: "Vegetarian", ar: "نباتي", ru: "Вегетарианское" } },
  { key: "vegan", icon: Sprout, color: "#2f8f83", label: { tr: "Vegan", en: "Vegan", ar: "نباتي صرف", ru: "Веганское" } },
  { key: "nuts", icon: Nut, color: "#a8702a", label: { tr: "Kuruyemiş içerir", en: "Contains nuts", ar: "يحتوي على مكسرات", ru: "Содержит орехи" } },
  { key: "gluten_free", icon: WheatOff, color: "#c99a2e", label: { tr: "Glutensiz", en: "Gluten free", ar: "خالٍ من الغلوتين", ru: "Без глютена" } },
  { key: "dairy", icon: Milk, color: "#5b7fbf", label: { tr: "Süt ürünü içerir", en: "Contains dairy", ar: "يحتوي على ألبان", ru: "Содержит молочное" } },
];

export const TagIcons = ({ tags, lang = "tr", withLabel = false }) => {
  const list = MENU_TAGS.filter((t) => tags?.includes(t.key));
  if (!list.length) return null;
  return (
    <span className="menu-tags" data-testid="menu-tags">
      {list.map(({ key, icon: Icon, color, label }) => (
        <span key={key} className="menu-tag" style={{ "--tag": color }} title={label[lang]} aria-label={label[lang]} data-testid={`menu-tag-${key}`}>
          <Icon size={12} />{withLabel && <span>{label[lang]}</span>}
        </span>
      ))}
    </span>
  );
};

export const TagPicker = ({ value, onChange }) => {
  const tags = value || [];
  const toggle = (k) => onChange(tags.includes(k) ? tags.filter((t) => t !== k) : [...tags, k]);
  return (
    <div className="tag-picker" data-testid="tags-field">
      <span className="recipe-title">Menü etiketleri (QR menüde simge olarak görünür)</span>
      <div>{MENU_TAGS.map(({ key, icon: Icon, color, label }) => (
        <button type="button" key={key} className={`tag-chip ${tags.includes(key) ? "on" : ""}`} style={{ "--tag": color }} onClick={() => toggle(key)} data-testid={`tag-toggle-${key}`}><Icon size={13} /> {label.tr}</button>
      ))}</div>
    </div>
  );
};
