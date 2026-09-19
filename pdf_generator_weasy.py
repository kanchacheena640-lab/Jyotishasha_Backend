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
# Line classification (Q2 / Q2.1 / Q4.2D). Every pattern below is applied to
# a single already-stripped line.
#
# A line that is ENTIRELY one bold span is one of two different things:
#   * a NUMBERED report-section heading -- "**3. Career Challenges**", the
#     structure every standard_v1 prompt (EN and HI, 208/208 headings)
#     prescribes -> a real <h2>;
#   * anything else ("**मुख्य बात:**", "**Astrology क्या कहती है:**",
#     "**Elevated**") -> a bold LEAD-IN paragraph, never a heading. Q2
#     promoted every whole-line bold span to <h2>, which turned each
#     lead-in into a full-size heading (Q4.2C visual defect).
# The inner text must not itself contain "**", so "**a** and **b**" is never
# mistaken for one whole-line span.
_WHOLE_LINE_BOLD = re.compile(r"^\*\*((?:(?!\*\*).)+?)\*\*(\s*:)?$")
# "N." / "N)" then a title. "3.5 points" is not a number (a digit follows the
# dot directly), while a title that itself starts with a digit is ("3. 4th House").
_NUMBERED_HEADING_TEXT = re.compile(r"^(\d{1,2})\s*[.)](?:\s+\S|(?=[^\d\s]))")

# The prompts say "report सादे text में", and the model sometimes emits NO
# markdown: numbered headings as plain "N. Title" lines and lead-ins as plain
# "Label:" lines (Q4.2D, Children). A plain numbered line is a heading only if
# it is title-like (short, no sentence punctuation), stands alone between
# blank lines and continues the 1, 2, 3... section sequence -- so a numbered
# LIST inside a section is never promoted. A plain colon-terminated short line
# after a blank line is a lead-in label.
_PLAIN_NUMBERED_HEADING = re.compile(r"^(\d{1,2})[.)]\s+(\S.{0,99})$")
# A trailing "?" is NOT sentence punctuation here: 7 Hindi prompts prescribe
# question-style headings ("1. Business में आपकी Suitability कैसी है?"), and a
# rejected first heading would also reject every later one via the sequence rule.
_SENTENCE_END = re.compile(r"[।.!:;,]$")
_PLAIN_LEAD_IN = re.compile(r"^[^\s\d*#•\-][^।!?*]{0,58}:$")

# A line made only of markdown marker characters is never content: with 3+
# marker characters it is a horizontal rule ("---", "***", "___", "- - -");
# with fewer it is a bare list marker (-, *, •). Neither may reach bullet or
# paragraph parsing (Q4.2D: "---" used to match the bullet rule and render
# as "• --").
_MARKER_ONLY_LINE = re.compile(r"^[-*_•\s]+$")

# A real bullet is a marker FOLLOWED BY whitespace (or the • glyph). The Q2.1
# pattern accepted a marker with no space, so any line starting with "**"
# ("**सीधी बात:** text") matched as a bullet whose text began with a stray
# "*" (Q4.2D), and "-5 degrees" lost its sign.
_BULLET_LINE = re.compile(r"^(?:[-*]\s+|•\s*)(.+)$")


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
    **N. Heading**       -> H2 (numbered report section)
    **Label:** (whole line) -> bold lead-in <p class='lead-in'>, NOT a heading
    - / * / • Text        -> real <li> in a <ul> (Q2.1); an EMPTY
                             marker line (nothing after it) renders
                             nothing at all, never an empty <li>.
    ---  ***  ___          -> horizontal rule: dropped, never a bullet
    @@Label: body         -> bold inline highlight
    **inline** bold        -> <strong> mid-sentence

    A heading never opens a content card by itself: the card is opened by
    the first content line under it, so a heading with no content (or one
    directly followed by another heading) emits no empty card.

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

    # Each non-blank line with whether a blank line (or the text edge) sits
    # directly before / after it -- plain-text headings and lead-ins are only
    # recognised as standalone lines.
    raw = [l.rstrip() for l in text.split("\n")]
    entries = [
        (l, i == 0 or not raw[i - 1].strip(), i == len(raw) - 1 or not raw[i + 1].strip())
        for i, l in enumerate(raw) if l.strip()
    ]
    html = []
    in_card = False
    in_list = False
    last_heading_no = 0

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

    for line, blank_before, blank_after in entries:
        stripped = line.strip()

        # ---------- MARKER-ONLY LINE: horizontal rule / bare bullet ----------
        if _MARKER_ONLY_LINE.match(stripped):
            if len(re.sub(r"\s", "", stripped)) >= 3:
                close_list()  # a horizontal rule ends any open list
            continue

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
            heading_text = line[3:].strip()
            num = _NUMBERED_HEADING_TEXT.match(heading_text)
            if num:
                last_heading_no = int(num.group(1))
            html.append(
                f"<h2 class='section-heading'>{heading_text}</h2>"
            )
            continue

        # ---------- H3 ----------
        if line.startswith("### "):
            close_list()
            close_card()
            html.append(
                f"<h3 class='sub-heading'>{line[4:].strip()}</h3>"
            )
            continue

        # ---------- WHOLE-LINE BOLD: numbered heading or lead-in ----------
        whole_line_match = _WHOLE_LINE_BOLD.match(stripped)
        if whole_line_match:
            inner = whole_line_match.group(1).strip()
            if whole_line_match.group(2):
                inner += ":"
            close_list()
            num = _NUMBERED_HEADING_TEXT.match(inner)
            if num:
                last_heading_no = int(num.group(1))
                close_card()
                html.append(f"<h2 class='section-heading'>{inner}</h2>")
            else:
                open_card()
                html.append(f"<p class='lead-in'><strong>{inner}</strong></p>")
            continue

        # ---------- PLAIN-TEXT NUMBERED HEADING / LEAD-IN ----------
        plain_heading = _PLAIN_NUMBERED_HEADING.match(stripped)
        if (plain_heading and blank_before and blank_after
                and int(plain_heading.group(1)) == last_heading_no + 1
                and not _SENTENCE_END.search(stripped)):
            last_heading_no = int(plain_heading.group(1))
            close_list()
            close_card()
            html.append(f"<h2 class='section-heading'>{stripped}</h2>")
            continue

        if blank_before and _PLAIN_LEAD_IN.match(stripped):
            close_list()
            open_card()
            html.append(f"<p class='lead-in'><strong>{stripped}</strong></p>")
            continue

        # ---------- BULLET LIST ITEM (Q2.1) ----------
        bullet_match = _BULLET_LINE.match(stripped)
        if bullet_match:
            open_card()
            if not in_list:
                html.append("<ul class='body-list'>")
                in_list = True
            html.append(f"<li>{_inline_bold(bullet_match.group(1).strip())}</li>")
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
    partner_info: dict | None = None,     # Q4.4B -- relationship_future_report only: {name, dob, tob, pob}
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
    # Whitelist only: coordinates, timezone, ids or mode fields can never reach the customer's PDF.
    display_partner_info = None
    if isinstance(partner_info, dict) and str(partner_info.get("name") or "").strip():
        display_partner_info = {k: partner_info[k] for k in ("name", "dob", "tob", "pob") if partner_info.get(k)}
        if display_partner_info.get("dob"):
            display_partner_info["dob"] = format_customer_date(display_partner_info["dob"])

    ctx = {
        "report_title": product.replace("_", " ").title(),
        "report_subtitle": report_subtitle,
        "is_sample": is_sample,
        "is_hindi": language == "hi",
        "lang": language,
        "today_str": today_str,
        "user_info": display_user_info,
        "partner_info": display_partner_info,
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
