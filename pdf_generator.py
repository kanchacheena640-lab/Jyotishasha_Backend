from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle, Flowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.graphics import renderPDF
from reportlab.pdfbase.ttfonts import TTFont
import os

FONT_DIR = "/home/Jyotishasha/fonts"

pdfmetrics.registerFont(
    TTFont("NotoSansDevanagari", os.path.join(FONT_DIR, "NotoSansDevanagari-Regular.ttf"))
)

# Flowable to draw the vector kundali on the page
class KundaliFlowable(Flowable):
    def __init__(self, drawing, width=400, height=400):
        super().__init__()
        self.drawing = drawing
        self.width = width
        self.height = height

    def wrap(self, availWidth, availHeight):
        return (self.width, self.height)

    def draw(self):
        # 0,0 from lower-left of the flowable box
        renderPDF.draw(self.drawing, self.canv, 0, 0)

def generate_pdf_report(
    output_path: str,
    user_info: dict,
    summary_blocks: dict,
    gpt_response: str,
    kundali_drawing,            # <- vector Drawing passed from tasks.py
    used_placeholders: list,
    product: str
):
    # ensure /reports exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=40,
        leftMargin=40,
        topMargin=50,
        bottomMargin=50,
        title="Astrology Report",
        author="Team Jyotishasha",
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="CustomTitle",
        fontSize=24,
        alignment=TA_CENTER,
        fontName="Helvetica",
        spaceAfter=20,
        textColor=colors.black
    ))
    styles.add(ParagraphStyle(
        name="Heading",
        fontSize=14,
        alignment=TA_LEFT,
        fontName="Helvetica",
        spaceAfter=10
    ))
    styles.add(ParagraphStyle(
        name="Body",
        fontSize=11,
        alignment=TA_LEFT,
        fontName="NotoSansDevanagari",
        spaceAfter=12,
        textColor=colors.black,
        leading=15 
    ))

    story = []

    # -----------------------------
    # Page 1 — Cover
    # -----------------------------
    story.append(Spacer(1, 2 * inch))
    report_title = product.replace("_", " ").title()
    story.append(Paragraph(f"Jyotishasha {report_title}", styles["CustomTitle"]))
    story.append(Spacer(1, 0.5 * inch))
    story.append(Paragraph(f"for: {user_info['name']}", styles["CustomTitle"]))
    story.append(Spacer(1, 0.2 * inch))

    from datetime import datetime
    today_str = datetime.now().strftime("%d %b %Y")
    story.append(Paragraph(f"Date: {today_str}", styles["CustomTitle"]))
    story.append(PageBreak())

    # -----------------------------
    # Page 2 — Client Snapshot + Kundali Chart
    # -----------------------------
    story.append(Paragraph("Client Snapshot", styles["Heading"]))
    snapshot = [
        ["Name", user_info.get("name", "")],
        ["Date of Birth", user_info.get("dob", "")],
        ["Time of Birth", user_info.get("tob", "")],
        ["Place of Birth", user_info.get("pob", "")],
    ]
    # Optional: Lagna sign from summary if present
    if "birth_chart_summary" in summary_blocks:
        try:
            snapshot.append(["Lagna Sign", summary_blocks["birth_chart_summary"].split()[3]])
        except Exception:
            pass

    table = Table(snapshot, colWidths=[120, 350])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "NotoSansDevanagari"),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(table)
    story.append(Spacer(1, 0.3 * inch))

    # Kundali chart
    story.append(Paragraph("Birth Chart (Kundali)", styles["Heading"]))
    story.append(Spacer(1, 0.2 * inch))
    story.append(KundaliFlowable(kundali_drawing, width=300, height=300))
    story.append(Spacer(1, 0.2 * inch))

    # Birth Chart Summary only on Page 2 if used
    if "birth_chart_summary" in used_placeholders and "birth_chart_summary" in summary_blocks:
        story.append(Paragraph("Birth Chart Summary", styles["Heading"]))
        story.append(Paragraph(summary_blocks["birth_chart_summary"], styles["Body"]))

    story.append(PageBreak())

    # -----------------------------
    # Page 3+ — Other Summaries + GPT Response
    # -----------------------------
    # Optional sections (only if in used_placeholders)
    if "mahadasha_summary" in used_placeholders and "mahadasha_summary" in summary_blocks:
        story.append(Paragraph("Mahadasha Summary", styles["Heading"]))
        story.append(Paragraph(summary_blocks["mahadasha_summary"], styles["Body"]))

    if "current_transit_summary" in used_placeholders and "current_transit_summary" in summary_blocks:
        story.append(Paragraph("Transit Summary", styles["Heading"]))
        story.append(Paragraph(summary_blocks["current_transit_summary"], styles["Body"]))

    if "aspect_summary" in used_placeholders and "aspect_summary" in summary_blocks:
        story.append(Paragraph("Planetary Aspects", styles["Heading"]))
        story.append(Paragraph(summary_blocks["aspect_summary"], styles["Body"]))

    if "manglik_summary" in used_placeholders and "manglik_summary" in summary_blocks:
        story.append(Paragraph("Manglik Status", styles["Heading"]))
        story.append(Paragraph(summary_blocks["manglik_summary"], styles["Body"]))

    # Personalized report (GPT)
    story.append(Paragraph("Personalized Astrology Report", styles["Heading"]))
    for line in gpt_response.split("\n"):
        if line.strip():
            story.append(Paragraph(line.strip(), styles["Body"]))

    # Final sign-off (must appear at very end)
    story.append(Spacer(1, 0.5 * inch))
    story.append(Paragraph(
        "With warm regards,<br/>Team Jyotishasha<br/>May your stars guide you to success.",
        styles["Body"]
    ))

    doc.build(story)
