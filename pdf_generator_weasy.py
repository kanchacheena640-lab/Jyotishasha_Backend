import os
import re
from datetime import datetime
from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML
from reportlab.graphics import renderSVG

# Q3 Batch 1 (visual QA correction round) -- shared presentation-layer
# date formatter (DD/MM/YYYY for every customer-facing date) and
# shared component-label localization (EN/HI), reused by tasks.py/
# modules/payments/report_q3_batch1.py too so the SAME rules apply
# everywhere a date or a shared component label reaches a customer.
from modules.payments.report_date_format import format_customer_date
from modules.payments.report_i18n_labels import labels_for_language

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
# Q2 -- a line that is ENTIRELY one bold span (nothing before/after the
# **...** pair once stripped) is the standard_v1 prompt family's own
# established section-heading convention (every one of the 24 standard
# prompts instructs the model to emit **Heading Name** on its own line,
# confirmed by direct inspection of all 25 prompts/*.txt files before
# this change) -- it was previously demoted to a bold PARAGRAPH by the
# generic "STAR BOLD FORMAT" rule below, which is the concrete,
# structural root cause of "weak information hierarchy" for all 24
# standard reports (their own real section headings never became real
# heading elements). Matched and rendered as a section heading BEFORE
# the generic star-bold fallback runs. relationship_future_report's own
# prompt (love_prompt_builder.py) explicitly instructs the model NOT to
# use ** at all (it uses #/##/###/@@ instead), so this new rule has
# nothing to match there and changes nothing for that pipeline.
_WHOLE_LINE_BOLD_HEADING = re.compile(r"^\*\*(.+?)\*\*$")

# Q2.1 -- Visual Polish. Root cause of the "three empty bullets before
# Business Orientation" QA finding: convert_headings() had NO markdown
# bullet-list handling at all before this fix. A GPT response line that
# is only a bare list marker (-, *, or a literal • with nothing else,
# or only whitespace after it -- a known LLM stray-formatting artifact)
# fell through every existing rule straight to the generic "Normal
# paragraph" branch and was rendered verbatim as its own <p>-</p> (or
# <p>*</p>/<p>•</p>). This is a STRUCTURAL parser fix, not a per-report
# CSS hide: a marker line with no real content after it is now dropped
# entirely (never rendered as an empty <li>), and -- the other half of
# the same fix -- a marker line that DOES have real content is now
# rendered as a genuine <li> inside a real <ul>, instead of a flat
# "<p>- some text</p>" paragraph (which is itself the correct answer to
# the general question of "does convert_headings() support markdown
# bullet lists at all" -- previously, no).
_BULLET_LINE = re.compile(r"^[-*•]\s*(.*)$")


def _inline_bold(text: str) -> str:
    """Shared inline **bold** -> <strong> substitution, reused by both
    the plain-paragraph branch and bullet-list items below (a bullet's
    own text may itself contain inline emphasis)."""
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)


def convert_headings(text: str, narrative_style: str = "card") -> str:
    """
    GPT -> HTML formatter (STRICT, PDF-safe)

    Rules:
    #  Heading           -> H1
    ## Heading           -> H2
    ### Heading          -> H3
    **Whole line bold**  -> H2 (Q2 -- see _WHOLE_LINE_BOLD_HEADING above)
    - / * / • Text        -> real <li> in a <ul> (Q2.1); an EMPTY
                             marker line (nothing after it) renders
                             nothing at all, never an empty <li>.
    @@Label: body         -> bold inline highlight
    **inline** bold        -> <strong> mid-sentence

    narrative_style (Q2.1, optional, default "card" -- preserves every
    existing caller's exact prior visual output byte-for-byte):
      "card" -> paragraphs/lists are wrapped in the existing beige
                '.card' shell (unchanged default behavior).
      "plain" -> paragraphs/lists render directly, no card shell --
                 gives Q3 a real lever (Section 6's "do not force every
                 section into a card") without Q2.1 guessing which of
                 the 25 products' sections should use it.
    """
    if not text:
        return ""

    use_card = narrative_style != "plain"

    lines = [l.rstrip() for l in text.split("\n") if l.strip()]
    html = []
    in_card = False
    in_list = False

    def open_card():
        nonlocal in_card
        if use_card and not in_card:
            html.append("<div class='card'>")
            in_card = True

    def close_card():
        nonlocal in_card
        if in_card:
            html.append("</div>")
            in_card = False

    def close_list():
        nonlocal in_list
        if in_list:
            html.append("</ul>")
            in_list = False

    for line in lines:
        stripped = line.strip()

        # ---------- H1 ----------
        if line.startswith("# ") and not line.startswith("##"):
            close_list()
            close_card()
            html.append(
                f"<h1 class='section-heading'>{line[2:].strip()}</h1>"
            )
            continue

        # ---------- H2 ----------
        if line.startswith("## ") and not line.startswith("###"):
            close_list()
            close_card()
            html.append(
                f"<h2 class='section-heading'>{line[3:].strip()}</h2>"
            )
            open_card()
            continue

        # ---------- H3 ----------
        if line.startswith("### "):
            close_list()
            close_card()
            html.append(
                f"<h3 class='sub-heading'>{line[4:].strip()}</h3>"
            )
            open_card()
            continue

        # ---------- WHOLE-LINE BOLD HEADING (Q2) ----------
        # **Business Orientation** on its own line, nothing else.
        whole_line_match = _WHOLE_LINE_BOLD_HEADING.match(stripped)
        if whole_line_match:
            close_list()
            close_card()
            html.append(
                f"<h2 class='section-heading'>{whole_line_match.group(1).strip()}</h2>"
            )
            open_card()
            continue

        # ---------- BULLET LIST ITEM (Q2.1) ----------
        bullet_match = _BULLET_LINE.match(stripped)
        if bullet_match:
            content = bullet_match.group(1).strip()
            if not content:
                # A bare "-"/"*"/"•" with nothing real after it -- the
                # exact shape of the reported artifact. Render nothing.
                continue
            open_card()
            if not in_list:
                html.append("<ul class='body-list'>")
                in_list = True
            html.append(f"<li>{_inline_bold(content)}</li>")
            continue
        else:
            close_list()

        # ---------- INLINE LABEL ----------
        # @@Varna: explanation
        if line.startswith("@@"):
            open_card()
            label, _, rest = line[2:].partition(":")
            html.append(
                f"<p><strong>{label.strip()}:</strong> {rest.strip()}</p>"
            )
            continue

        # ---------- STAR BOLD FORMAT ----------
        # **important text** mixed inline with other text on the line.
        if "**" in line:
            open_card()
            html.append(f"<p>{_inline_bold(line)}</p>")
            continue

        # ---------- Normal paragraph ----------
        open_card()
        html.append(f"<p>{line}</p>")

    close_list()
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
    logo_src: str | None = None,    # e.g. "static/logo.png"
    # -----------------------------------------------------------
    # Q2/Q2.1 -- Premium PDF visual foundation. Every parameter below
    # is OPTIONAL and defaults to "render nothing"
    # (None/[]/False/"en"/"card"), so every existing call site
    # (tasks.py, modules/love/love_premium_task.py) continues to
    # produce exactly the same component set as before this phase --
    # only the shared cover/page-flow/heading-hierarchy/footer
    # improvements apply automatically. WHICH components a given
    # report actually populates (result_cards, tables, a gemstone box,
    # a disclaimer, etc.) is a Q3 decision, made per report product,
    # not here.
    #
    # Q2.1 LOCKED RULE: the only shared closing CTA this module
    # supports is `app_download` (Jyotishasha App download only -- no
    # consultation/gemstone-purchase/cross-sell CTA capability exists
    # here at all anymore; Q2's original generic `cta` parameter was
    # removed, not just left unused, specifically so no future caller
    # can accidentally reintroduce an off-brand CTA through it).
    # -----------------------------------------------------------
    report_subtitle: str | None = None,
    is_sample: bool = False,
    language: str = "en",
    narrative_style: str = "card",        # Q2.1 -- "card" (default, unchanged) or "plain"
    answer_hero: dict | None = None,      # Q2.1 -- {label, value, interpretation, evidence:[...], timing, caution}
    result_cards: list | None = None,     # [{label, value, detail}]
    fact_cards: list | None = None,       # [{heading, text, items:[...]}]
    timeline: dict | None = None,         # {heading, entries:[{label, date_range, note, current}]}
    tables: list | None = None,           # [{heading, headers:[...], rows:[[...]]}]
    action_list: dict | None = None,      # Q2.1 -- {heading, items:[...]} numbered guidance list
    notices: list | None = None,          # [{heading, text}]
    highlights: list | None = None,       # [{heading, text}]
    gemstone: dict | None = None,         # Q2.1 -- {planet, gemstone, substone, reason, caution}
    disclaimer: str | None = None,
    app_download: dict | None = None,     # Q2.1 -- {heading, benefit_text, play_store_url, app_store_url}
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
    # Q3 Batch 1 (visual QA correction) -- ALL customer-facing dates use
    # the shared DD/MM/YYYY presentation formatter; canonical/internal
    # date storage (Order.dob's own ISO "YYYY-MM-DD" column, kundali/
    # dasha/transit calculation) is completely untouched -- only how a
    # date STRING is displayed here changes.
    today_str = format_customer_date(datetime.now())
    display_user_info = dict(user_info or {})
    if display_user_info.get("dob"):
        display_user_info["dob"] = format_customer_date(display_user_info["dob"])

    ctx = {
        "report_title": product.replace("_", " ").title(),
        "report_subtitle": report_subtitle,
        "is_sample": is_sample,
        "is_hindi": language == "hi",
        "lang": language,
        "today_str": today_str,
        "user_info": display_user_info,
        "kundali_img_src": kundali_rel,
        "logo_src": logo_src,
        "fonts_dir_rel": FONTS_REL,
        # Q3 Batch 1 -- shared, renderer-level localized labels for the
        # small set of fixed component strings (gemstone box, timing
        # label, action-list heading, app-download CTA) -- see
        # modules/payments/report_i18n_labels.py's own docstring.
        "labels": labels_for_language(language),

        # Summaries (only if used) -- unchanged Q1/Q1.5 contract, same
        # keys, same "only if the prompt actually references it" gate.
        "birth_chart_summary": _to_html(summary_blocks.get("birth_chart_summary")) if "birth_chart_summary" in used_placeholders else "",
        "mahadasha_summary": _to_html(summary_blocks.get("mahadasha_summary")) if "mahadasha_summary" in used_placeholders else "",
        "current_transit_summary": _to_html(summary_blocks.get("current_transit_summary")) if "current_transit_summary" in used_placeholders else "",
        "aspect_summary": _to_html(summary_blocks.get("aspect_summary")) if "aspect_summary" in used_placeholders else "",
        "manglik_summary": _to_html(summary_blocks.get("manglik_summary")) if "manglik_summary" in used_placeholders else "",

        # Q2/Q2.1 reusable premium components -- always a safe,
        # iterable/falsy default so every {% for %}/{% if %} in the
        # template is a no-op when a caller (every current one)
        # doesn't supply it.
        "answer_hero": answer_hero,
        "result_cards": result_cards or [],
        "fact_cards": fact_cards or [],
        "timeline": timeline,
        "tables": tables or [],
        "action_list": action_list,
        "notices": notices or [],
        "highlights": highlights or [],
        "gemstone": gemstone,
        "disclaimer": disclaimer,
        "app_download": app_download,

        # ✅ Final GPT response converted via numbered parser
        "gpt_response_html": convert_headings(gpt_response, narrative_style=narrative_style),

    }

    # ✅ Step 3: Render to HTML and convert to PDF
    html = env.get_template("report_template.html").render(**ctx)
    HTML(string=html, base_url=BASE_DIR).write_pdf(output_path)

    return output_path
