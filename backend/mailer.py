import os
import smtplib
import ssl
from email.message import EmailMessage


def tl(value) -> str:
    return f"{float(value or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " ₺"


def qty(value) -> str:
    return f"{float(value or 0):g}".replace(".", ",")


def low_stock_text(items: list) -> str:
    if not items:
        return "Kritik stok: Tüm malzemeler minimum seviyenin üzerinde."
    lines = [f"- {i['name']}: {qty(i.get('quantity'))} {i.get('unit', '')} (minimum {qty(i.get('minimum'))})" for i in items]
    return "KRİTİK STOK — minimum seviyenin altına düşen malzemeler:\n" + "\n".join(lines)


def _send(subject: str, body: str, attachment: tuple[bytes, str] | None = None, to: str | None = None) -> None:
    sender, password, recipient = os.environ["GMAIL_USERNAME"], os.environ["GMAIL_APP_PASSWORD"], to or os.environ["REPORT_RECIPIENT"]
    msg = EmailMessage()
    msg["From"] = f"GÖKBOSS POS <{sender}>"
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(body)
    if attachment:
        msg.add_attachment(attachment[0], maintype="application", subtype="pdf", filename=attachment[1])
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30) as smtp:
        smtp.login(sender, password.replace(" ", ""))
        smtp.send_message(msg)


def restaurant_text(r: dict) -> str:
    rec, pay = r["reconciliation"], r["payments"]
    cash = (f"Kasa: beklenen {tl(rec['expected_closing'])} · sayılan {tl(rec['actual_closing'])} · fark {tl(rec['difference'])}" if rec["has_closing"]
            else f"Kasa: beklenen {tl(rec['expected_closing'])} · KAPANIŞ GİRİLMEDİ")
    return (f"■ {r['name'].upper()}\n  Ciro: {tl(r['revenue'])} ({r['sales_count']} işlem) · Gider: {tl(r['expenses'])} · Kâr: {tl(r['profit'])}\n"
            f"  Nakit {tl(pay.get('Nakit'))} · Kart {tl(pay.get('Kart'))} · Yemek kartı {tl(pay.get('Yemek kartı'))}\n  {cash}\n"
            f"  Kritik stok: {', '.join(i['name'] for i in r['low_stock']) or 'yok'}")


def send_report_email(pdf: bytes, report: dict, day: str) -> None:
    rec = report["reconciliation"]
    per = "\n\n".join(restaurant_text(r) for r in report.get("restaurants", []))
    _send(
        f"GÖKBOSS POS — Gün sonu raporu {day}",
        f"Merhaba,\n\n{day} tarihli gün sonu raporunuz ektedir.\n\n"
        f"TÜM RESTORANLAR\nToplam ciro: {tl(report['revenue'])}\nToplam gider: {tl(report['expenses'])}\nNet kâr: {tl(report['profit'])}\n"
        f"Satış işlemi: {report['sales_count']}\nToplam kasa farkı: {tl(rec['difference'])}\n\n{per}\n\n{low_stock_text(report.get('low_stock', []))}\n\nGÖKBOSS POS",
        (pdf, f"gokboss-pos-gun-sonu-{day}.pdf"),
    )


def send_weekly_email(report: dict, label: str) -> None:
    top = report["top_products"][:5]
    lines = [f"{i + 1}. {p['product_name']} — {qty(p['quantity'])} adet · ciro {tl(p['revenue'])} · kâr {tl(p['profit'])}" for i, p in enumerate(top)] or ["Bu hafta satış yok."]
    margin = round(report["profit"] / report["revenue"] * 100) if report["revenue"] else 0
    _send(
        f"GÖKBOSS POS — Haftalık özet {label}",
        f"Merhaba,\n\nGeçen haftanın özeti ({label}):\n\n"
        f"Toplam ciro: {tl(report['revenue'])}\nToplam gider: {tl(report['expenses'])}\nNet kâr: {tl(report['profit'])} (%{margin})\nSatış işlemi: {report['sales_count']}\n\n"
        "En çok satanlar:\n" + "\n".join(lines) + "\n\nİyi haftalar,\nGÖKBOSS POS",
    )


MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


def send_monthly_email(report: dict, payroll: dict, month: str) -> None:
    y, m = month.split("-")
    label = f"{MONTHS[int(m) - 1]} {y}"
    top = report["top_products"][:5]
    lines = [f"{i + 1}. {p['product_name']} — {qty(p['quantity'])} adet · ciro {tl(p['revenue'])}" for i, p in enumerate(top)] or ["Bu ay satış yok."]
    t = payroll["totals"]
    net_after_payroll = report["profit"] - t["total_pay"]
    _send(
        f"GÖKBOSS POS — Aylık özet {label}",
        f"Merhaba,\n\n{label} özeti:\n\n"
        f"Toplam gelir: {tl(report['revenue'])}\nToplam gider: {tl(report['expenses'])}\nBrüt kâr: {tl(report['profit'])}\nSatış işlemi: {report['sales_count']}\n\n"
        f"Bordro (brüt): {tl(t['total_pay'])} · fazla mesai {qty(t['overtime_hours'])} saat · avans {tl(t['advance_total'])}\n"
        f"Bordro sonrası kâr (tahmini): {tl(net_after_payroll)}\n\n"
        "En çok satanlar:\n" + "\n".join(lines) + "\n\nİyi çalışmalar,\nGÖKBOSS POS",
    )


def send_leave_request_email(staff_name: str, doc: dict) -> None:
    def d(v):
        y, m, day = v.split("-")
        return f"{day}.{m}.{y}"
    period = d(doc["start"]) if doc["start"] == doc["end"] else f"{d(doc['start'])} – {d(doc['end'])}"
    _send(
        f"GÖKBOSS POS — Yeni izin talebi: {staff_name}",
        f"Merhaba,\n\n{staff_name} yeni bir izin talebi gönderdi.\n\nTarih: {period} ({doc['days']} gün)\nTür: {doc['type']}\n"
        f"Not: {doc.get('note') or '—'}\n\nOnaylamak veya reddetmek için GÖKBOSS POS > Ekip & Vardiya > İzin talepleri bölümüne gidin.\n\nGÖKBOSS POS",
    )


def send_cash_reminder_email(rec: dict) -> None:
    y, m, d = rec["date"].split("-")
    pays = rec.get("payments", {})
    _send(
        f"GÖKBOSS POS — {rec.get('restaurant', '')} kasa kapanışı girilmedi ({d}.{m}.{y})",
        f"Merhaba,\n\n{rec.get('restaurant', 'Restoran')} için bugünün kasa kapanışı henüz girilmedi.\n\n"
        f"Bugünkü satış: {tl(rec['sales'])} (nakit {tl(pays.get('Nakit'))} · kart {tl(pays.get('Kart'))} · yemek kartı {tl(pays.get('Yemek kartı'))})\n"
        f"Bugünkü gider: {tl(rec['expenses'])}\nBeklenen kasa (nakit): {tl(rec['expected_closing'])}\n\n"
        "Lütfen GÖKBOSS POS > Kasa bölümünden açılış ve kapanış tutarlarını girin.\n\nGÖKBOSS POS",
    )


def send_restaurant_daily_email(r: dict, day: str, to: str) -> None:
    _send(f"{r['name']} — Gün sonu özeti {day}", f"Merhaba,\n\n{day} tarihli {r['name']} gün sonu özetiniz:\n\n{restaurant_text(r)}\n\nGÖKBOSS POS", to=to)


def send_pin_request_email(restaurant: str, email: str) -> None:
    _send(f"{restaurant} — şifre sıfırlama talebi", f"Merhaba,\n\n{email} hesabı {restaurant} için yeni şifre talep etti.\nOnaylamak için panelde Kullanıcılar > Restoranlar bölümüne gidin.\n\nGÖKBOSS POS")
