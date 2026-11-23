from io import BytesIO
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FONT_DIR = Path(__file__).parent / "fonts"
pdfmetrics.registerFont(TTFont("Sans", str(FONT_DIR / "LiberationSans-Regular.ttf")))
pdfmetrics.registerFont(TTFont("Sans-Bold", str(FONT_DIR / "LiberationSans-Bold.ttf")))

PERIOD_LABELS = {"daily": "Günlük", "weekly": "Haftalık", "monthly": "Aylık"}
AMBER = "D97706"


def tl(value) -> str:
    text = f"{float(value or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{text} ₺"


def _sections(report: dict) -> list:
    rec = report["reconciliation"]
    return [
        ("Dönem Özeti", ["Kalem", "Tutar"], [
            ["Toplam ciro", report["revenue"]], ["Toplam gider", report["expenses"]],
            ["Net kâr", report["profit"]], ["Satış adedi (işlem)", report["sales_count"]]]),
        ("Kasa Mutabakatı (Bugün)", ["Kalem", "Tutar"], [
            ["Açılış kasası", rec["opening"]], ["+ Günlük satış", rec["sales"]], ["− Günlük gider", rec["expenses"]],
            ["Beklenen kapanış", rec["expected_closing"]], ["Gerçek kapanış", rec["actual_closing"]], ["Fark", rec["difference"]]]),
        ("Ürün Performansı", ["Ürün", "Adet", "Ciro", "Maliyet", "Kâr"], [
            [p["product_name"], p["quantity"], p["revenue"], p["cost"], p["profit"]] for p in report["top_products"]]),
        ("Satış Kayıtları", ["Tarih", "Ürün", "Kanal", "Adet", "Birim fiyat", "Tutar"], [
            [s.get("created_at", "")[:16].replace("T", " "), s.get("product_name") or s.get("note") or "-", s.get("channel", ""),
             s.get("quantity", 1), s.get("unit_price", 0), s.get("amount", 0)] for s in report["sales"]]),
        ("Gider Kayıtları", ["Tarih", "Kategori", "Açıklama", "Tutar"], [
            [e.get("created_at", "")[:16].replace("T", " "), e.get("category", ""), e.get("note", ""), e.get("amount", 0)] for e in report["expenses_list"]]),
    ]


MONEY_HEADERS = {"Tutar", "Ciro", "Maliyet", "Kâr", "Birim fiyat"}


def build_excel(report: dict) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Rapor"
    ws.append([f"GÖKBOSS POS — {PERIOD_LABELS[report['period']]} Rapor"])
    ws["A1"].font = Font(size=14, bold=True)
    ws.append([f"Dönem: {report['start'][:10]} — {report['end'][:10]}"])
    for title, headers, rows in _sections(report):
        ws.append([])
        ws.append([title])
        ws.cell(ws.max_row, 1).font = Font(bold=True, size=12, color=AMBER)
        ws.append(headers)
        for cell in ws[ws.max_row]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1F2937")
        if not rows:
            ws.append(["Kayıt yok"])
        for row in rows:
            ws.append(row)
            for idx, header in enumerate(headers, start=1):
                if header in MONEY_HEADERS:
                    ws.cell(ws.max_row, idx).number_format = '#,##0.00 "₺"'
            if headers == ["Kalem", "Tutar"] and isinstance(row[1], (int, float)) and "adedi" not in row[0]:
                ws.cell(ws.max_row, 2).number_format = '#,##0.00 "₺"'
            elif headers == ["Kalem", "Tutar"]:
                ws.cell(ws.max_row, 2).number_format = "0"
    for col, width in zip(range(1, 7), [22, 26, 22, 14, 16, 16]):
        ws.column_dimensions[get_column_letter(col)].width = width
    for row in ws.iter_rows():
        for cell in row:
            cell.alignment = Alignment(vertical="center")
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _fmt(header: str, value, is_kalem_money: bool):
    if header in MONEY_HEADERS and (header != "Tutar" or is_kalem_money):
        return tl(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def build_pdf(report: dict) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
                            title="GÖKBOSS POS Rapor")
    title = ParagraphStyle("t", fontName="Sans-Bold", fontSize=18, leading=22)
    sub = ParagraphStyle("s", fontName="Sans", fontSize=10, textColor=colors.HexColor("#6B7280"), leading=14)
    h2 = ParagraphStyle("h", fontName="Sans-Bold", fontSize=12, textColor=colors.HexColor(f"#{AMBER}"), spaceBefore=10, spaceAfter=6)
    cell = ParagraphStyle("c", fontName="Sans", fontSize=8.5, leading=11)
    story = [Paragraph(f"GÖKBOSS POS — {PERIOD_LABELS[report['period']]} Rapor", title),
             Paragraph(f"Dönem: {report['start'][:10]} — {report['end'][:10]}", sub), Spacer(1, 6)]
    for name, headers, rows in _sections(report):
        story.append(Paragraph(name, h2))
        kalem = headers == ["Kalem", "Tutar"]
        body = [[Paragraph(_fmt(h, v, not (kalem and "adedi" in str(r[0]))), cell) for h, v in zip(headers, r)] for r in rows]
        if not body:
            body = [[Paragraph("Kayıt yok", cell)] + [""] * (len(headers) - 1)]
        table = Table([[Paragraph(f"<b>{h}</b>", cell) for h in headers]] + body, repeatRows=1,
                      colWidths=[doc.width / len(headers)] * len(headers))
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F4F6")),
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#E5E7EB")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(table)
    doc.build(story)
    return buf.getvalue()
