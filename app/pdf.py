"""PDF-Kostenaufstellung für eine Angebotsanfrage.

Verwendet die beim Absenden gespeicherte Kalkulation (Snapshot), damit das PDF auch nach
späteren Preisänderungen im Admin genau das zeigt, was der Kunde gesehen hat.
"""
from io import BytesIO
from xml.sax.saxutils import escape

from itsdangerous import BadSignature, URLSafeSerializer
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .config import settings
from .models import QuoteRequest

MUTED = colors.HexColor("#5c5c5c")
LINE = colors.HexColor("#d4d4d4")

# --------------------------------------------------------------------------- signierte Download-Links

_signer = URLSafeSerializer(settings.secret_key, salt="quote-request-pdf")


def pdf_token(request_id: int) -> str:
    return _signer.dumps(request_id)


def verify_pdf_token(token: str, request_id: int) -> bool:
    try:
        return _signer.loads(token) == request_id
    except BadSignature:
        return False


# --------------------------------------------------------------------------- Formatierung

def _eur(cent: int) -> str:
    s = f"{cent / 100:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def _pct(bp: int) -> str:
    return f"{bp / 100:g}".replace(".", ",") + " %"


_styles = getSampleStyleSheet()
H1 = ParagraphStyle("h1", parent=_styles["Heading1"], fontName="Helvetica-Bold", fontSize=18, spaceAfter=2)
H2 = ParagraphStyle("h2", parent=_styles["Heading2"], fontName="Helvetica-Bold", fontSize=11.5,
                    spaceBefore=12, spaceAfter=6)
BODY = ParagraphStyle("body", parent=_styles["BodyText"], fontName="Helvetica", fontSize=9.5, leading=13)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=8, leading=10, textColor=MUTED)
RIGHT = ParagraphStyle("right", parent=BODY, alignment=TA_RIGHT)
BRAND = ParagraphStyle("brand", parent=BODY, fontName="Helvetica-Bold", fontSize=13)


def _p(text: str, style=BODY) -> Paragraph:
    return Paragraph(escape(str(text)).replace("\n", "<br/>"), style)


def _price_rows(q: dict) -> list[list]:
    rows: list[list] = []

    def row(label, value, sub=None, bold=False, color=None):
        label_html = f"<b>{escape(label)}</b>" if bold else escape(label)
        if sub:
            label_html += f"<br/><font size=8 color='#5c5c5c'>{escape(sub)}</font>"
        value_html = f"<b>{escape(value)}</b>" if bold else escape(value)
        style = BODY if not color else ParagraphStyle("c", parent=BODY, textColor=color)
        rstyle = RIGHT if not color else ParagraphStyle("cr", parent=RIGHT, textColor=color)
        rows.append([Paragraph(label_html, style), Paragraph(value_html, rstyle)])

    pkg = q.get("package")
    if pkg:
        sub = " · ".join(x for x in [f"Sender: {pkg['station']}" if pkg.get("station") else "",
                                     f"{pkg['spots']} Ausstrahlungen" if pkg.get("spots") else "", "Pauschalpreis",
                                     f"Sendegebiet: {pkg['coverage']}" if pkg.get("coverage") else "",
                                     *[l.strip() for l in pkg.get("description", "").splitlines() if l.strip()]] if x)
        row(f"Komplettpaket „{pkg['name']}“" + (f" (Art.-Nr. {pkg['article_no']})" if pkg.get("article_no") else ""),
            _eur(pkg["price_cent"]), sub)
    p = q.get("production")
    if p:
        if p.get("studio"):
            row("Studiospot mit echtem Sprecher", "inklusive" if p.get("in_package") else _eur(p["total_cent"]),
                f"{p['seconds']} Sek." + (" · im Komplettpaket enthalten" if p.get("in_package") else ""))
        elif p.get("total_cent"):  # Anfragen aus älteren Versionen mit Produktionspreis
            row(f"Spotproduktion {p['seconds']} Sek.", _eur(p["total_cent"]))
        else:
            row("Spot-Text & Hörbeispiel", "gratis", f"{p['seconds']} Sek.")
    for l in q.get("lines", []):
        row(f"{l['spots']} × {l['station']}", _eur(l["total_cent"]),
            f"{'Stream · ' if l.get('kind') == 'stream' else ''}{l['time_slot']} · {l['seconds']} Sek. · à {_eur(l['unit_price_cent'])}"
            + (f" · Sendegebiet: {l['coverage']}" if l.get("coverage") else ""))
    for a in q.get("addons", []):
        row(a["name"], _eur(a["price_cent"]))
    for d in q.get("discounts", []):
        row(d["name"], "− " + _eur(d["amount_cent"]), color=colors.HexColor("#1e7a43"))
    row("Netto", _eur(q["net_cent"]), bold=True)
    if q.get("ad_tax_cent"):
        row(f"Werbeabgabe {_pct(q['ad_tax_rate_bp'])}", _eur(q["ad_tax_cent"]),
            f"auf {_eur(q['ad_tax_base_cent'])} Radio-Sendezeit")
    if q.get("reverse_charge"):
        row("MwSt. 0 % – Nettorechnung", _eur(0),
            "Steuerschuldnerschaft des Leistungsempfängers (Reverse Charge)")
    else:
        vat_label = f"MwSt. {_pct(q['vat_rate_bp'])}"
        if q.get("country_name"):
            vat_label += f" ({q['country_name']})"
        row(vat_label, _eur(q["vat_cent"]))
    row("Gesamt (netto, Reverse Charge)" if q.get("reverse_charge") else "Gesamt brutto", _eur(q["gross_cent"]), bold=True)
    return rows


def _logo(path, max_w=70 * mm, max_h=14 * mm):
    """Logo-Bild im Seitenverhältnis, höchstens max_w × max_h; None, wenn es nicht lesbar ist."""
    try:
        w, h = ImageReader(str(path)).getSize()
    except Exception:  # noqa: BLE001 – defektes Bild → Schriftzug statt Abbruch
        return None
    scale = min(max_w / w, max_h / h)
    img = Image(str(path), width=w * scale, height=h * scale)
    img.hAlign = "LEFT"
    return img


def build_request_pdf(req: QuoteRequest, company_info: str, accent: str = "#e4002b", logo_path=None,
                      tagline: str = "sound so(u)lutions — Wien") -> bytes:
    """accent: Akzentfarbe aus Admin → Design (Linie oben, Logo-Akzent); logo_path: Logo-Bild (PNG/JPG/WebP)."""
    buf = BytesIO()

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(20 * mm, 12 * mm, company_info)
        canvas.drawRightString(190 * mm, 12 * mm, f"Seite {doc.page}")
        canvas.setStrokeColor(colors.HexColor(accent))
        canvas.setLineWidth(3)
        canvas.line(20 * mm, 287 * mm, 190 * mm, 287 * mm)
        canvas.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=18 * mm, bottomMargin=20 * mm,
                            title=f"Anfrage {req.id}", author="onaircraft")
    q, b, cfg = req.quote or {}, req.brief or {}, req.configuration or {}
    width = doc.width - 12  # nutzbare Breite (Frame hat 6 pt Innenabstand je Seite)
    story: list = []

    logo = _logo(logo_path) if logo_path else None
    story.append(logo or Paragraph(f"on<font color='{accent}'>air</font>craft", BRAND))
    story.append(_p(tagline, SMALL))
    story.append(Spacer(1, 10 * mm))
    story.append(_p(f"Kostenaufstellung zur Anfrage Nr. {req.id}", H1))
    story.append(_p(f"vom {req.created_at.strftime('%d.%m.%Y')} · unverbindlich", SMALL))

    # Kunde & Spot nebeneinander
    def kv_table(pairs, total=None):
        data = [[_p(k, SMALL), _p(v)] for k, v in pairs if v]
        t = Table(data, colWidths=[28 * mm, (total or width / 2 - 2 * mm) - 28 * mm], hAlign="LEFT")
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 2), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        return t

    prod = q.get("production") or {}
    customer = kv_table([
        ("Name", req.customer_name), ("Firma", req.company or b.get("firma", "")),
        ("Adresse", "\n".join(x for x in [req.street, f"{req.zip_code} {req.city}".strip()] if x)),
        ("Telefon", req.phone), ("E-Mail", req.email),
        ("Land", q.get("country_name", "")), ("UID-Nummer", q.get("vat_id") or ""),
    ])
    spot = kv_table([
        ("Variante", "Studiospot mit echtem Sprecher" if prod.get("studio") else "Text & Hörbeispiel"),
        ("Paket", (q.get("package") or {}).get("name", "")),
        ("Länge", f"{prod['seconds']} Sek." if prod.get("seconds") else ""),
        ("Anlass", b.get("occasion", "")), ("Tonalität", b.get("tonality", "")),
        ("Sprachstil", b.get("language_style", "")), ("Musik", prod.get("music") or ""),
    ])
    cols = Table([[_p("Kunde", H2), _p("Spot", H2)], [customer, spot]], colWidths=[width / 2] * 2, hAlign="LEFT")
    cols.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story.append(Spacer(1, 4 * mm))
    story.append(cols)

    if b.get("botschaft") or b.get("cta"):
        story.append(_p("Inhalt", H2))
        story.append(kv_table([("Kernbotschaft", b.get("botschaft", "")), ("Call-to-Action", b.get("cta", ""))],
                              total=width))
    if b.get("script"):
        script = Table([[_p(b["script"])]], colWidths=[width], hAlign="LEFT")
        script.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f4f4f4")),
                                    ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                                    ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                                    ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8)]))
        story.append(KeepTogether([_p("Spot-Text", H2), script]))

    if q:
        rows = _price_rows(q)
        t = Table(rows, colWidths=[width - 40 * mm, 40 * mm], hAlign="LEFT")
        n = len(rows)
        style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                 ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINE),
                 ("LINEABOVE", (0, n - 1), (-1, n - 1), 1.2, colors.black),
                 ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
        t.setStyle(TableStyle(style))
        story.append(KeepTogether([_p("Kosten", H2), t]))
        if cfg.get("promo_code"):
            story.append(Spacer(1, 2 * mm))
            story.append(_p(f"Gutscheincode: {cfg['promo_code']}", SMALL))

    if req.message:
        story.append(_p("Nachricht", H2))
        story.append(_p(req.message))

    consent = getattr(req, "consent", None) or {}
    if consent:
        accepted = next(iter(consent.values())).get("accepted_at", "")[:16].replace("T", " ")
        parts = [f"{c.get('title', k)} (Version {c.get('version', '–')})" for k, c in consent.items()]
        story.append(Spacer(1, 4 * mm))
        story.append(_p(f"Zugestimmt: {' und '.join(parts)} am {accepted} UTC.", SMALL))

    story.append(Spacer(1, 8 * mm))
    story.append(_p("Diese Aufstellung ist unverbindlich und stellt keine Rechnung dar. Alle Preise in Euro. "
                    "Text und Hörbeispiel sind kostenlos; ein Studiospot wird vor der Ausstrahlung zur Freigabe "
                    "vorgelegt. Die Buchung der Sendezeit erfolgt erst nach Ihrer Bestätigung.", SMALL))

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
