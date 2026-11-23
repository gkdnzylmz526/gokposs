import os
import smtplib
import ssl
from email.message import EmailMessage


def tl(value) -> str:
    return f"{float(value or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " ₺"


def send_report_email(pdf: bytes, report: dict, day: str) -> None:
    sender, password, recipient = os.environ["GMAIL_USERNAME"], os.environ["GMAIL_APP_PASSWORD"], os.environ["REPORT_RECIPIENT"]
    rec = report["reconciliation"]
    msg = EmailMessage()
    msg["From"] = f"GÖKBOSS POS <{sender}>"
    msg["To"] = recipient
    msg["Subject"] = f"GÖKBOSS POS — Gün sonu raporu {day}"
    msg.set_content(
        f"Merhaba,\n\n{day} tarihli gün sonu raporunuz ektedir.\n\n"
        f"Toplam ciro: {tl(report['revenue'])}\nToplam gider: {tl(report['expenses'])}\nNet kâr: {tl(report['profit'])}\n"
        f"Satış işlemi: {report['sales_count']}\nKasa farkı: {tl(rec['difference'])}\n\nGÖKBOSS POS"
    )
    msg.add_attachment(pdf, maintype="application", subtype="pdf", filename=f"gokboss-pos-gun-sonu-{day}.pdf")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30) as smtp:
        smtp.login(sender, password.replace(" ", ""))
        smtp.send_message(msg)
