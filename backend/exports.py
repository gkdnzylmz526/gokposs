from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo
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
pdfmetrics.registerFont(TTFont("Sans", str(FONT_DIR / "NotoSans-Regular.ttf")))
pdfmetrics.registerFont(TTFont("Sans-Bold", str(FONT_DIR / "NotoSans-Bold.ttf")))
pdfmetrics.registerFontFamily("Sans", normal="Sans", bold="Sans-Bold", italic="Sans", boldItalic="Sans-Bold")

PERIOD_LABELS = {"daily": "Günlük", "weekly": "Haftalık", "monthly": "Aylık", "custom": "Özel Aralık"}
AMBER = "D97706"


def tl(value) -> str:
    text = f"{float(value or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{text} ₺"


def _local(value: str) -> str:
    return datetime.fromisoformat(value).astimezone(ZoneInfo("Europe/Istanbul")).strftime("%d.%m.%Y %H:%M")


def _sections(report: dict) -> list:
    rec = report["reconciliation"]
    return [
        ("Dönem Özeti", ["Kalem", "Tutar"], [
            ["Toplam ciro", report["revenue"]], ["Toplam gider", report["expenses"]],
            ["Net kâr", report["profit"]], ["Satış adedi (işlem)", report["sales_count"]]]),
        ("Kasa Mutabakatı (" + report["reconciliation"]["date"] + ")", ["Kalem", "Tutar"], [
            ["Açılış kasası", rec["opening"]], ["+ Günlük satış", rec["sales"]], ["− Günlük gider", rec["expenses"]],
            ["Beklenen kapanış", rec["expected_closing"]], ["Gerçek kapanış", rec["actual_closing"]], ["Fark", rec["difference"]]]),
        ("Ürün Performansı", ["Ürün", "Adet", "Ciro", "Maliyet", "Kâr"], [
            [p["product_name"], p["quantity"], p["revenue"], p["cost"], p["profit"]] for p in report["top_products"]]),
        ("Satış Kayıtları", ["Tarih", "Ürün", "Kanal", "Adet", "Birim fiyat", "Tutar"], [
            [_local(s.get("created_at")), s.get("product_name") or s.get("note") or "-", s.get("channel", ""),
             s.get("quantity", 1), s.get("unit_price", 0), s.get("amount", 0)] for s in report["sales"]]),
        ("Gider Kayıtları", ["Tarih", "Kategori", "Açıklama", "Tutar"], [
            [_local(e.get("created_at")), e.get("category", ""), e.get("note", ""), e.get("amount", 0)] for e in report["expenses_list"]]),
    ] + ([("Kritik Stok", ["Malzeme", "Mevcut", "Minimum", "Birim"], [
        [i["name"], i.get("quantity", 0), i.get("minimum", 0), i.get("unit", "")] for i in report["low_stock"]])] if "low_stock" in report else [])


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


def build_payroll_excel(data: dict) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Maaş Özeti"
    ws.append([f"GÖKBOSS POS — {data['month']} Maaş Raporu"])
    ws["A1"].font = Font(size=14, bold=True)
    ws.append([f"Haftalık {data['weekly_limit']} saati aşan çalışma fazla mesai sayılır (x{data['overtime_rate']})"])
    ws.append([])
    headers = ["Personel", "Görev", "Saatlik ücret", "Vardiya", "Normal saat", "Fazla mesai saati", "Normal ücret", "Fazla mesai ücreti", "Brüt toplam", "Avans", "Net ödenecek", "İzin günü"]
    ws.append(headers)
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F2937")
    money_cols = {3, 7, 8, 9, 10, 11}
    for r in data["rows"]:
        ws.append([r["name"], r["task"], r["hourly_wage"], r["shift_count"], r["regular_hours"], r["overtime_hours"], r["regular_pay"], r["overtime_pay"], r["total_pay"], r["advance_total"], r["net_pay"], r["leave_days"]])
        for c in money_cols:
            ws.cell(ws.max_row, c).number_format = '#,##0.00 "₺"'
    t = data["totals"]
    ws.append(["TOPLAM", "", "", "", t["regular_hours"], t["overtime_hours"], t["regular_pay"], t["overtime_pay"], t["total_pay"], t["advance_total"], t["net_pay"], t["leave_days"]])
    for c in range(1, 13):
        ws.cell(ws.max_row, c).font = Font(bold=True)
    for c in money_cols:
        ws.cell(ws.max_row, c).number_format = '#,##0.00 "₺"'
    for col, width in zip(range(1, 13), [22, 16, 14, 10, 13, 17, 15, 18, 15, 13, 15, 10]):
        ws.column_dimensions[get_column_letter(col)].width = width
    detail = wb.create_sheet("Vardiya Detayı")
    detail.append(["Personel", "Tarih", "Başlangıç", "Bitiş", "Saat", "Fazla mesai saati", "Görev"])
    for cell in detail[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F2937")
    for r in data["rows"]:
        for sh in r["shifts"]:
            detail.append([r["name"], datetime.fromisoformat(sh["date"]).strftime("%d.%m.%Y"), sh["start"], sh["end"], sh["hours"], sh["overtime"], sh.get("task", "")])
    for col, width in zip(range(1, 8), [22, 13, 11, 11, 9, 17, 18]):
        detail.column_dimensions[get_column_letter(col)].width = width
    adv = wb.create_sheet("Avanslar")
    adv.append(["Personel", "Tarih", "Tutar", "Not"])
    for cell in adv[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F2937")
    for r in data["rows"]:
        for a in r["advances"]:
            adv.append([r["name"], datetime.fromisoformat(a["date"]).strftime("%d.%m.%Y"), a["amount"], a.get("note", "")])
            adv.cell(adv.max_row, 3).number_format = '#,##0.00 "₺"'
    for col, width in zip(range(1, 5), [22, 13, 14, 30]):
        adv.column_dimensions[get_column_letter(col)].width = width
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_payslip_pdf(row: dict, data: dict) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm, title=f"Bordro {row['name']}")
    title = ParagraphStyle("t", fontName="Sans-Bold", fontSize=18, leading=22)
    sub = ParagraphStyle("s", fontName="Sans", fontSize=10, textColor=colors.HexColor("#6B7280"), leading=14)
    h2 = ParagraphStyle("h", fontName="Sans-Bold", fontSize=11, textColor=colors.HexColor(f"#{AMBER}"), spaceBefore=12, spaceAfter=6)
    cell = ParagraphStyle("c", fontName="Sans", fontSize=9, leading=12)
    month = datetime.fromisoformat(f"{data['month']}-01")
    months = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]

    def table(rows, widths, bold_last=False):
        t = Table([[Paragraph(str(c), cell) for c in r] for r in rows], colWidths=widths)
        style = [("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#E5E7EB")), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("ALIGN", (-1, 0), (-1, -1), "RIGHT")]
        if bold_last:
            style += [("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#FEF3C7")), ("FONTNAME", (0, -1), (-1, -1), "Sans-Bold")]
        t.setStyle(TableStyle(style))
        return t

    w = doc.width
    story = [Paragraph("GÖKBOSS POS — Ücret Bordrosu", title), Paragraph(f"{months[month.month - 1]} {month.year} · {row['name']}{' · ' + row['task'] if row.get('task') else ''}", sub)]
    story += [Paragraph("Çalışma özeti", h2), table([
        ["Vardiya sayısı", row["shift_count"]], ["Normal çalışma", f"{row['regular_hours']:g} saat"], ["Fazla mesai", f"{row['overtime_hours']:g} saat"],
        ["İzin günü", row["leave_days"]], ["Saatlik ücret", tl(row["hourly_wage"])]], [w * 0.65, w * 0.35])]
    story += [Paragraph("Ödeme", h2), table([
        ["Normal ücret", tl(row["regular_pay"])], [f"Fazla mesai ücreti (x{data['overtime_rate']:g})", tl(row["overtime_pay"])], ["Brüt toplam", tl(row["total_pay"])],
        ["Avans kesintisi", f"− {tl(row['advance_total'])}"], ["NET ÖDENECEK", tl(row["net_pay"])]], [w * 0.65, w * 0.35], bold_last=True)]
    if row["advances"]:
        story += [Paragraph("Avanslar", h2), table([[datetime.fromisoformat(a["date"]).strftime("%d.%m.%Y"), a.get("note") or "—", tl(a["amount"])] for a in row["advances"]], [w * 0.25, w * 0.5, w * 0.25])]
    if row["shifts"]:
        story += [Paragraph("Vardiya detayı", h2), table([["Tarih", "Saat", "Süre", "Fazla mesai"]] + [[datetime.fromisoformat(s["date"]).strftime("%d.%m.%Y"), f"{s['start']}–{s['end']}", f"{s['hours']:g} sa", f"{s['overtime']:g} sa" if s["overtime"] else "—"] for s in row["shifts"]], [w * 0.3, w * 0.3, w * 0.2, w * 0.2])]
    story += [Spacer(1, 24), Paragraph(f"Haftalık {data['weekly_limit']} saati aşan çalışma fazla mesai olarak hesaplanmıştır. Bu belge bilgilendirme amaçlıdır.", sub),
              Spacer(1, 30), table([["İşveren imza", "Personel imza"]], [w * 0.5, w * 0.5])]
    doc.build(story)
    return buf.getvalue()
