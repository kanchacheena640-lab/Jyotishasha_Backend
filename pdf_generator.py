from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.graphics import renderPDF

# Register Unicode font for Hindi support
pdfmetrics.registerFont(UnicodeCIDFont("HeiseiMin-W3"))

def generate_pdf_report(
    output_path: str,
    user_info: dict,
    summary_blocks: dict,
    gpt_response: str,
    kundali_drawing,  # 🔑 ab Drawing aayega, path nahi
    used_placeholders: list,
    product: str
):
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=40,
        leftMargin=40,
        topMargin=50,
        bottomMargin=50,
        title="Astrology Report",
        author="Team Jyotishasha"
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="CustomTitle",
        fontSize=24,
        alignment=TA_CENTER,
        fontName="HeiseiMin-W3",
        spaceAfter=20,
        textColor=colors.black
    ))
    styles.add(ParagraphStyle(name="Heading", fontSize=14, alignment=TA_LEFT,
                              fontName="HeiseiMin-W3", spaceAfter=10))
    styles.add(ParagraphStyle(name="Body", fontSize=11, alignment=TA_LEFT,
                              fontName="HeiseiMin-W3", spaceAfter=12))

    story = []

    # 1. Cover Page
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

    # Recipient Page
    story.append(Paragraph(f"Prepared especially for", styles["Body"]))
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph(f"<b>{user_info['name']}</b>", styles["CustomTitle"]))
    story.append(Spacer(1, 4.5 * inch))
    story.append(Paragraph("With blessings,", styles["Body"]))
    story.append(Paragraph("🙏 Team Jyotishasha 🙏", styles["CustomTitle"]))
    story.append(PageBreak())

    # 2. Client Snapshot
    story.append(Paragraph("Client Snapshot", styles["Heading"]))
    snapshot = [
        ["Name", user_info["name"]],
        ["Date of Birth", user_info["dob"]],
        ["Time of Birth", user_info["tob"]],
        ["Place of Birth", user_info["pob"]],
    ]
    if "birth_chart_summary" in summary_blocks:
        snapshot.append(["Lagna Sign",
                         summary_blocks["birth_chart_summary"].split()[3]])
    table = Table(snapshot, colWidths=[120, 350])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "HeiseiMin-W3"),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(table)
    story.append(Spacer(1, 0.3 * inch))

    # 3. Kundali Chart (vector drawing)
    story.append(Paragraph("Birth Chart (Kundali)", styles["Heading"]))
    story.append(Spacer(1, 0.2 * inch))

    def draw_chart(canvas, doc):
        # draw kundali_drawing at center of page
        renderPDF.draw(kundali_drawing, canvas,
                       x=doc.width/2 - 200,  # center align
                       y=doc.height/2 - 200)

    story.append(Spacer(1, 4.5 * inch))
    doc.build(story, onFirstPage=draw_chart, onLaterPages=draw_chart)

    # ⚠️ Note: Agar tumhe chart sirf ek hi page pe chahiye
    # to `onFirstPage` me draw_chart rakho aur `onLaterPages=None` use karo.
