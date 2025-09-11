import os
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

# Helper to convert plain text to HTML (line breaks)
def _to_html(text: str | None) -> str:
    if not text:
        return ""
    return "<br/>".join([line.strip() for line in text.split("\n") if line.strip()])

# Main function
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
        "kundali_img_src": kundali_rel,      # ✅ now an SVG path
        "logo_src": logo_src,
        "fonts_dir_rel": FONTS_REL,

        # Summaries (only if used)
        "birth_chart_summary": _to_html(summary_blocks.get("birth_chart_summary")) if "birth_chart_summary" in used_placeholders else "",
        "mahadasha_summary": _to_html(summary_blocks.get("mahadasha_summary")) if "mahadasha_summary" in used_placeholders else "",
        "current_transit_summary": _to_html(summary_blocks.get("current_transit_summary")) if "current_transit_summary" in used_placeholders else "",
        "aspect_summary": _to_html(summary_blocks.get("aspect_summary")) if "aspect_summary" in used_placeholders else "",
        "manglik_summary": _to_html(summary_blocks.get("manglik_summary")) if "manglik_summary" in used_placeholders else "",

        # Main GPT body
        "gpt_response_html": _to_html(gpt_response),
    }

    # ✅ Step 3: Render to HTML and convert to PDF
    html = env.get_template("report_template.html").render(**ctx)
    HTML(string=html, base_url=BASE_DIR).write_pdf(output_path)

    return output_path
