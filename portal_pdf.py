"""Printable operational lists and source-labelled summaries, without scoring."""
from __future__ import annotations

import io
import json
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether

NAVY = colors.HexColor("#073b5b")


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="FTitle", parent=styles["Title"], textColor=NAVY, fontSize=23, leading=28, alignment=0, spaceAfter=12))
    styles.add(ParagraphStyle(name="FCell", parent=styles["Normal"], textColor=NAVY, fontSize=8, leading=11))
    styles.add(ParagraphStyle(name="FHead", parent=styles["FCell"], textColor=colors.white, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="FSmall", parent=styles["Normal"], textColor=colors.HexColor("#53697e"), fontSize=9, leading=13, spaceAfter=10))
    return styles


def _safe(value):
    return escape(str(value if value is not None else "—"))


def _analysis_entries(value, path=""):
    """Present every source field without assigning units or financial meaning."""
    if isinstance(value, dict) and value:
        for key, child in value.items():
            yield from _analysis_entries(child, (path + " / " if path else "") + str(key))
    elif isinstance(value, list) and value:
        for index, child in enumerate(value, 1):
            yield from _analysis_entries(child, f"{path} [{index}]")
    else:
        rendered = "Non indicato" if value is None else ("Sì" if value is True else "No" if value is False else json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else str(value))
        yield path or "Esito", rendered


def _page_number(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#53697e"))
    canvas.drawString(doc.leftMargin, 22, "FinancePlus · Dati del MASTER · Uso nel perimetro autorizzato")
    canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, 22, f"Pagina {doc.page}")
    canvas.restoreState()


def list_pdf(title, headers, rows, filters, role, source, scope):
    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=30, leftMargin=30, topMargin=34, bottomMargin=40, title=title, author="FinancePlus")
    now = datetime.now(ZoneInfo("Europe/Rome")).strftime("%d/%m/%Y %H:%M %Z")
    filter_text = "; ".join(f"{k}: {v}" for k, v in filters.items() if v) or "Nessun filtro"
    story = [Paragraph("FINANCEPLUS.TECH", styles["FSmall"]), Paragraph(_safe(title), styles["FTitle"]),
             Paragraph(_safe(f"{scope} · {len(rows)} righe · {now} · Ruolo: {role}"), styles["FSmall"]),
             Paragraph("Filtri: " + _safe(filter_text), styles["FSmall"]),
             Paragraph("Fonte: " + _safe(source), styles["FSmall"])]
    body = [[Paragraph(_safe(h), styles["FHead"]) for h in headers]]
    body += [[Paragraph(_safe(v), styles["FCell"]) for v in row] for row in rows]
    if not rows:
        body.append([Paragraph("Nessun risultato", styles["FCell"])] + [""] * (len(headers) - 1))
    widths = [doc.width / len(headers)] * len(headers)
    if len(headers) == 6:
        widths = [doc.width * n for n in (.22, .20, .16, .12, .15, .15)]
    table = Table(body, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f6f9")]), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 9), ("LINEBELOW", (0, 0), (-1, -1), .3, colors.HexColor("#d9e4eb"))]))
    story.append(table)
    doc.build(story, onFirstPage=_page_number, onLaterPages=_page_number)
    return buffer.getvalue()


def source_report(bundle):
    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=38, leftMargin=38, topMargin=40, bottomMargin=42, title="Riepilogo Cliente 360", author="FinancePlus")
    company = bundle["client"]
    now = datetime.now(ZoneInfo("Europe/Rome")).strftime("%d/%m/%Y %H:%M %Z")
    story = [Paragraph("FINANCEPLUS.TECH", styles["FSmall"]), Paragraph("Riepilogo Cliente 360", styles["FTitle"]),
             Paragraph(_safe(company.get("name")), styles["Heading2"]),
             Paragraph(_safe(f"ID MASTER: {company['id']} · P. IVA: {company.get('vat') or 'Non disponibile'}"), styles["FSmall"]),
             Paragraph(_safe(f"Esportato il {now}. Fonte: {bundle.get('source') or 'SMART F+ · proiezione cloud autorizzata'}"), styles["FSmall"]),
             Paragraph("Questo documento riporta le informazioni ricevute dal MASTER. Non avvia una nuova analisi, non aggiorna una pratica e non costituisce una delibera di finanziamento.", styles["FSmall"])]
    story.append(Paragraph("Richieste", styles["Heading2"]))
    if bundle.get("requests_loaded") is False:
        story.append(Paragraph("Elenco parziale: il servizio ha raggiunto il limite di 100 richieste per fascicolo.", styles["FSmall"]))
    for practice in bundle.get("requests", []):
        values = [f"ID {practice.get('id')}: {practice.get('title') or 'Richiesta'}", f"Stato: {practice.get('status') or 'Non disponibile'}", f"Importo: {practice.get('amount') if practice.get('amount') is not None else 'Non disponibile'}", f"Finalità: {practice.get('purpose') or 'Non indicata'}", f"Istituto: {practice.get('institution') or 'Non indicato'}"]
        story.append(Paragraph("<br/>".join(_safe(v) for v in values), styles["FSmall"]))
    if not bundle.get("requests"):
        story.append(Paragraph("Nessuna richiesta disponibile.", styles["FSmall"]))
    story.append(Paragraph("Analisi disponibile nel MASTER", styles["Heading2"]))
    payload = bundle.get("analysis")
    if payload is None:
        story.append(Paragraph("Nessuna analisi disponibile. Non sono stati sostituiti i valori mancanti con dati dimostrativi.", styles["FSmall"]))
    else:
        story.append(Paragraph("Campi e valori come trasmessi dal MASTER. Le etichette originali sono mantenute; non vengono aggiunte unità, valutazioni o interpretazioni.", styles["FSmall"]))
        for label, value in _analysis_entries(payload):
            story.append(Paragraph("<b>" + _safe(label) + "</b><br/>" + _safe(value).replace("\n", "<br/>"), styles["FSmall"]))
        story.append(Spacer(1, 12))
    story.append(Paragraph("Documenti ricevuti dalla proiezione", styles["Heading2"]))
    if bundle.get("documents_loaded") is False:
        story.append(Paragraph("Metadati documentali parziali: il servizio ha raggiunto il limite di 100 documenti per fascicolo.", styles["FSmall"]))
    for document in bundle.get("documents", []):
        story.append(Paragraph(_safe(f"{document.get('title') or 'Documento'} · {document.get('category') or 'Categoria non indicata'} · {document.get('date') or 'Data non indicata'}"), styles["FSmall"]))
    if not bundle.get("documents"):
        story.append(Paragraph("Nessun metadato documentale disponibile in questa vista.", styles["FSmall"]))
    doc.build(story, onFirstPage=_page_number, onLaterPages=_page_number)
    return buffer.getvalue()
