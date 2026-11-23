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


def _send(subject: str, body: str, attachment: tuple[bytes, str] | None = None) -> None:
    sender, password, recipient = os.environ["GMAIL_USERNAME"], os.environ["GMAIL_APP_PASSWORD"], os.environ["REPORT_RECIPIENT"]
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


def send_report_email(pdf: bytes, report: dict, day: str) -> None:
    rec = report["reconciliation"]
    _send(
        f"GÖKBOSS POS — Gün sonu raporu {day}",
        f"Merhaba,\n\n{day} tarihli gün sonu raporunuz ektedir.\n\n"
        f"Toplam ciro: {tl(report['revenue'])}\nToplam gider: {tl(report['expenses'])}\nNet kâr: {tl(report['profit'])}\n"
        f"Satış işlemi: {report['sales_count']}\nKasa farkı: {tl(rec['difference'])}\n\n{low_stock_text(report.get('low_stock', []))}\n\nGÖKBOSS POS",
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
