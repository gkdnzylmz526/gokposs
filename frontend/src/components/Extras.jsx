import { QRCodeSVG } from "qrcode.react";
import { toast } from "sonner";
import { Copy, Printer, QrCode, Trash2 } from "lucide-react";

const money = (n) => new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY", maximumFractionDigits: 2 }).format(n || 0);

export const PaymentSummary = ({ payments, wasteCost, wasteCount }) => {
  if (!payments) return null;
  const total = Object.values(payments).reduce((a, b) => a + b, 0) || 1;
  return (
    <section className="panel payment-summary" data-testid="payment-summary">
      <div className="panel-head"><div><h3>Ödeme türleri & fire</h3><span className="muted">Seçili dönem</span></div></div>
      <div className="pay-grid">
        {Object.entries(payments).map(([k, v]) => (
          <div key={k} className="pay-box" data-testid={`payment-${k}`}><span>{k}</span><b>{money(v)}</b><i style={{ width: `${(v / total) * 100}%` }} /></div>
        ))}
        <div className="pay-box waste" data-testid="report-waste"><span>Fire maliyeti</span><b>{money(wasteCost)}</b><small>{wasteCount || 0} kayıt</small></div>
      </div>
    </section>
  );
};

export const WasteLog = ({ items, onAdd, onDelete }) => (
  <section className="panel table-panel waste-panel" data-testid="waste-log">
    <div className="panel-head movements-head">
      <div><h3>Fire ve atık</h3><span className="muted">Bozulan, dökülen veya tarihi geçen malzemeler stoktan düşülür, maliyeti raporlara yansır</span></div>
      <button className="primary-button" data-testid="add-waste-button" onClick={() => onAdd("waste")}>+ Fire kaydı</button>
    </div>
    <div className="table-head" style={{ gridTemplateColumns: "1fr 1.2fr .8fr 1.2fr .8fr 40px" }}><span>Tarih</span><span>Malzeme</span><span>Miktar</span><span>Neden</span><span>Maliyet</span><span /></div>
    {!items.length && <div className="empty-state">Henüz fire kaydı yok.</div>}
    {items.map((w, i) => (
      <div className="table-row" style={{ gridTemplateColumns: "1fr 1.2fr .8fr 1.2fr .8fr 40px" }} key={w.id} data-testid={`waste-row-${i}`}>
        <span>{new Date(w.created_at).toLocaleDateString("tr-TR")}</span><span>{w.inventory_name}</span><span>{Number(w.quantity).toLocaleString("tr-TR")} {w.unit}</span>
        <span>{w.reason}{w.note ? ` · ${w.note}` : ""}</span><span className="table-amount danger-text">{money(w.cost)}</span>
        <button className="icon-button" title="Sil" data-testid={`waste-delete-${i}`} onClick={() => window.confirm("Fire kaydı silinsin mi? Miktar stoka geri eklenir.") && onDelete("waste", w.id)}><Trash2 size={14} /></button>
      </div>
    ))}
  </section>
);

export const MenuQR = () => {
  const url = `${window.location.origin}/menu`;
  const copy = async () => { try { await navigator.clipboard.writeText(url); toast.success("Menü linki kopyalandı"); } catch { toast.error("Kopyalanamadı"); } };
  const print = () => { const w = window.open("", "_blank"); w.document.write(`<html><head><title>GÖKPOS QR Menü</title></head><body style="font-family:sans-serif;text-align:center;padding:40px">${document.getElementById("menu-qr").innerHTML}<h1 style="margin:16px 0 4px">GÖKPOS</h1><p>Menümüzü görmek için QR kodu okutun</p></body></html>`); w.document.close(); w.print(); };
  return (
    <section className="panel menu-qr" data-testid="menu-qr">
      <div id="menu-qr" className="qr-box"><QRCodeSVG value={url} size={150} /></div>
      <div className="qr-text">
        <h3><QrCode size={18} /> QR menü</h3>
        <p className="muted">Masalara koyun; müşteriler okutunca aktif ürünler ve güncel fiyatlar telefonlarında açılır. Fiyat değiştirdiğinizde menü kendiliğinden güncellenir.</p>
        <a href={url} target="_blank" rel="noreferrer" data-testid="menu-qr-link">{url}</a>
        <div className="report-actions"><button className="secondary-button" data-testid="menu-qr-copy" onClick={copy}><Copy size={14} /> Linki kopyala</button><button className="secondary-button" data-testid="menu-qr-print" onClick={print}><Printer size={14} /> Yazdır</button></div>
      </div>
    </section>
  );
};
