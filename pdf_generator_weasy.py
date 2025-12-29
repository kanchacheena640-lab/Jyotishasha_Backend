import os
import re
from datetime import datetime
from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML
from reportlab.graphics import renderSVG

# Base paths
BASE_DIR = os.path.dirname(__file__)
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
FONTS_REL = "fonts"   # Used in CSS via relative path
TMP_REL = "tmp"       # Where kundali SVG will be saved

# Setup Jinja2
env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(['html', 'xml'])
)

# Helper to convert linebreak text to <br/>
def _to_html(text: str | None) -> str:
    if not text:
        return ""
    return "<br/>".join([line.strip() for line in text.split("\n") if line.strip()])

# ✅ NEW: Convert GPT plain numbered text to HTML-formatted headings + paragraphs
def convert_headings(text: str) -> str:
    """
    GPT → HTML formatter (STRICT, PDF-safe)

    Rules:
    #  Heading      → H1
    ## Heading      → H2
    ### Heading     → H3
    -**Text:** body → bold inline highlight
    """
    if not text:
        return ""

    lines = [l.rstrip() for l in text.split("\n") if l.strip()]
    html = []
    in_card = False

    def open_card():
        nonlocal in_card
        if not in_card:
            html.append("<div class='card hi'>")
            in_card = True

    def close_card():
        nonlocal in_card
        if in_card:
            html.append("</div>")
            in_card = False

    for line in lines:

        # ---------- H1 ----------
        if line.startswith("# ") and not line.startswith("##"):
            close_card()
            html.append(
                f"<h1 class='section-heading'>{line[2:].strip()}</h1>"
            )
            continue

        # ---------- H2 ----------
        if line.startswith("## ") and not line.startswith("###"):
            close_card()
            html.append(
                f"<h2 class='section-heading'>{line[3:].strip()}</h2>"
            )
            open_card()
            continue

        # ---------- H3 ----------
        if line.startswith("### "):
            close_card()
            html.append(
                f"<h3 class='sub-heading'>{line[4:].strip()}</h3>"
            )
            open_card()
            continue

        # ---------- Bold inline bullet ----------
        # -**Varna (1/1):** text
        if line.startswith("-**") and "**" in line:
            open_card()
            clean = line.lstrip("-").strip()
            clean = re.sub(
                r"\*\*(.+?)\*\*",
                r"<strong>\1</strong>",
                clean
            )
            html.append(f"<p>{clean}</p>")
            continue

        # ---------- Normal paragraph ----------
        open_card()
        html.append(f"<p>{line}</p>")

    close_card()
    return "\n".join(html)

# ✅ Main function
def generate_pdf_report_weasy(
    output_path: str,
    user_info: dict,
    summary_blocks: dict,
    gpt_response: str,
    kundali_drawing,                # ReportLab Drawing
    used_placeholders: list,
    product: str,
    logo_src: str | None = None     # e.g. "static/logo.png"
):
    # Ensure folders exist
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    os.makedirs(os.path.join(BASE_DIR, TMP_REL), exist_ok=True)

    # ✅ Step 1: Kundali Drawing → SVG export
    kundali_rel = None
    if kundali_drawing is not None:
        svg_filename = f"kundali_{int(datetime.now().timestamp())}.svg"
        kundali_rel = os.path.join(TMP_REL, svg_filename)        # relative path
        kundali_abs = os.path.join(BASE_DIR, kundali_rel)        # absolute path
        renderSVG.drawToFile(kundali_drawing, kundali_abs)

    # ✅ Step 2: Context for Jinja template
    today_str = datetime.now().strftime("%d %b %Y")
    ctx = {
        "report_title": product.replace("_", " ").title(),
        "today_str": today_str,
        "user_info": user_info,
        "kundali_img_src": kundali_rel,
        "logo_src": logo_src,
        "fonts_dir_rel": FONTS_REL,

        # Summaries (only if used)
        "birth_chart_summary": _to_html(summary_blocks.get("birth_chart_summary")) if "birth_chart_summary" in used_placeholders else "",
        "mahadasha_summary": _to_html(summary_blocks.get("mahadasha_summary")) if "mahadasha_summary" in used_placeholders else "",
        "current_transit_summary": _to_html(summary_blocks.get("current_transit_summary")) if "current_transit_summary" in used_placeholders else "",
        "aspect_summary": _to_html(summary_blocks.get("aspect_summary")) if "aspect_summary" in used_placeholders else "",
        "manglik_summary": _to_html(summary_blocks.get("manglik_summary")) if "manglik_summary" in used_placeholders else "",

        # ✅ Final GPT response converted via numbered parser
        "gpt_response_html": convert_headings(gpt_response),

    }

    # ✅ Step 3: Render to HTML and convert to PDF
    html = env.get_template("report_template.html").render(**ctx)
    HTML(string=html, base_url=BASE_DIR).write_pdf(output_path)

    return output_path
