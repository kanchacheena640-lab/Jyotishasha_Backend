# pdf_generator_weasy.py
import os
from datetime import datetime
from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML
from reportlab.graphics import renderPM  # Kundali drawing -> PNG

BASE_DIR = os.path.dirname(__file__)
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
FONTS_REL = "fonts"   # CSS me relative path se font load hoga
TMP_REL = "tmp"       # yahin PNG save karenge (relative to BASE_DIR)

env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(['html', 'xml'])
)

def _to_html(text: str | None) -> str:
    if not text:
        return ""
    # \n -> <br/> for paragraphs
    return "<br/>".join([line.strip() for line in text.split("\n") if line.strip()])

def generate_pdf_report_weasy(
    output_path: str,
    user_info: dict,
    summary_blocks: dict,
    gpt_response: str,
    kundali_drawing,            # ReportLab Drawing (same as before)
    used_placeholders: list,
    product: str,
    logo_src: str | None = None   # e.g. "static/logo.png" (relative), or None
):
    # Ensure folders
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    os.makedirs(os.path.join(BASE_DIR, TMP_REL), exist_ok=True)

    # 1) Kundali Drawing -> PNG (relative path so WeasyPrint can resolve with base_url)
    kundali_rel = None
    if kundali_drawing is not None:
        kundali_rel = os.path.join(TMP_REL, f"kundali_{int(datetime.now().timestamp())}.png")
        kundali_abs = os.path.join(BASE_DIR, kundali_rel)
        renderPM.drawToFile(kundali_drawing, kundali_abs, fmt="PNG")

    # 2) Context for template
    today_str = datetime.now().strftime("%d %b %Y")
    ctx = {
        "report_title": product.replace("_", " ").title(),
        "today_str": today_str,
        "user_info": user_info,
        "kundali_img_src": kundali_rel,     # relative path
        "logo_src": logo_src,               # keep relative if possible (e.g. "static/logo.png")
        "fonts_dir_rel": FONTS_REL,         # used by @font-face in CSS

        # Summaries (only if used)
        "birth_chart_summary": _to_html(summary_blocks.get("birth_chart_summary")) if "birth_chart_summary" in used_placeholders else "",
        "mahadasha_summary": _to_html(summary_blocks.get("mahadasha_summary")) if "mahadasha_summary" in used_placeholders else "",
        "current_transit_summary": _to_html(summary_blocks.get("current_transit_summary")) if "current_transit_summary" in used_placeholders else "",
        "aspect_summary": _to_html(summary_blocks.get("aspect_summary")) if "aspect_summary" in used_placeholders else "",
        "manglik_summary": _to_html(summary_blocks.get("manglik_summary")) if "manglik_summary" in used_placeholders else "",

        # GPT body
        "gpt_response_html": _to_html(gpt_response),
    }

    # 3) Render HTML and write PDF
    html = env.get_template("report_template.html").render(**ctx)
    HTML(string=html, base_url=BASE_DIR).write_pdf(output_path)
    return output_path
