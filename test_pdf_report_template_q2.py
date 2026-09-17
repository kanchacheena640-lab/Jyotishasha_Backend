"""
test_pdf_report_template_q2.py
-------------------------------------------------
Q2 / Q2.1 -- Premium Paid Report PDF Visual Foundation + Visual Polish
verification. Q2 is not yet approved/committed; this file is amended
in place (rather than split into a separate Q2.1 file) to reflect the
corrected, current design -- unlike Q1/Q1.5, which are frozen.

No DB/Flask/Order/payment/email dependency -- pdf_generator_weasy.py
and templates/report_template.html are pure functions of their inputs.
Every check here is either (a) a direct string assertion on the
rendered HTML or (b) an actual WeasyPrint render() call verifying page
count/A4 sizing/no-crash for real. Genuine VISUAL quality is not
something an automated test can certify -- that is why this phase also
produces human-reviewable QA PDFs separately.

Covers:
  A. Cover system (Page 1) -- real product title, optional subtitle,
     optional SAMPLE marker, and Q2.1's locked rule: the cover contains
     NOTHING else (no answer hero, no fact card, no CTA) ever.
  B. Page-2 Primary Answer Hero (Q2.1) -- absent by default (legacy
     compatibility), renders label/value/interpretation/evidence/
     timing/caution when supplied, and -- the critical product rule --
     renders BEFORE the Kundali snapshot in document order.
  C. App-download-only closing CTA (Q2.1) -- absent by default, the
     ONLY shared closing CTA capability that exists (the old generic
     `cta` parameter/consultation copy is gone, not just unused),
     optional store URLs render only when supplied, no fake links.
  D. Disclaimer slot.
  E. Reusable component system -- result card, fact card, timeline,
     table, notice, highlight, numbered action/guidance list (Q2.1),
     gemstone recommendation (Q2.1, locked "no data -> no render, no
     filler copy" rule).
  F. Relationship pipeline compatibility.
  G. Hindi/Unicode.
  H. convert_headings() -- heading-hierarchy fix (unchanged from Q2)
     AND the Q2.1 empty-bullet-artifact fix (bare "-"/"*"/"•"
     marker lines render nothing; real bullet lines become real <li>
     elements; narrative_style="plain" skips the card shell).
  I. Page-flow structure.
  J. Footer / page-numbering.
  K. A4 sizing.
  L. Existing/legacy generation compatibility (both the pre-Q2 and the
     Q2 pre-Q2.1 call shapes still work with zero new required param).
"""

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from weasyprint import HTML

from pdf_generator_weasy import (
    env, convert_headings, generate_pdf_report_weasy, BASE_DIR,
)
from kundali_chart_generator import generate_kundali_drawing
# Q3 Batch 1 (visual QA correction round) -- generate_pdf_report_weasy()
# now always supplies a `labels` dict to the template (see report_i18n_
# labels.py); this file's own _base_ctx() renders the template directly,
# bypassing that function, so it must supply the same shape itself --
# labels_for_language("en") is the exact real value generate_pdf_report_
# weasy() would build for language="en".
from modules.payments.report_i18n_labels import labels_for_language

passed = 0
failed = 0


def check(label, condition):
    global passed, failed
    if condition:
        print(f"  PASS: {label}")
        passed += 1
    else:
        print(f"  FAIL: {label}")
        failed += 1


PLANETS = [
    {"name": "Sun", "house": 1, "sign": "Leo", "aspecting": []},
    {"name": "Moon", "house": 4, "sign": "Scorpio", "aspecting": []},
]


def _base_ctx(**overrides):
    ctx = dict(
        report_title="Startup Suggestion Report",
        report_subtitle=None,
        is_sample=False,
        is_hindi=False,
        lang="en",
        today_str="17 Sep 2026",
        user_info={"name": "Test User", "dob": "1990-06-15", "tob": "10:30", "pob": "Delhi, India"},
        kundali_img_src=None,
        logo_src=None,
        fonts_dir_rel="fonts",
        birth_chart_summary="You have a Leo Ascendant.",
        mahadasha_summary="You are in Saturn Mahadasha.",
        current_transit_summary="Saturn is in Pisces.",
        aspect_summary="",
        manglik_summary="",
        answer_hero=None,
        result_cards=[],
        fact_cards=[],
        timeline=None,
        tables=[],
        action_list=None,
        notices=[],
        highlights=[],
        gemstone=None,
        disclaimer=None,
        app_download=None,
        gpt_response_html="<div class='card'><p>Body content.</p></div>",
        labels=labels_for_language("en"),
    )
    ctx.update(overrides)
    return ctx


def render(**overrides):
    return env.get_template("report_template.html").render(**_base_ctx(**overrides))


def body_of(html):
    return html.split("<body", 1)[1]


def cover_of(html):
    return html.split('class="cover-page">', 1)[1].split("</div>", 1)[0]


# =================================================================
print("=== A: Cover system (Page 1) ===")
# =================================================================
html = render(report_title="Startup Suggestion Report")
check("A: cover shows the real product title", "<div class=\"cover-title\">Startup Suggestion Report</div>" in html)
check("A: 'Personalized Astrology Report' text no longer appears anywhere", "Personalized Astrology Report" not in html)

html_subtitle = render(report_subtitle="A grounded, chart-based reading")
check("A: optional subtitle renders when supplied", "<div class=\"cover-subtitle\">A grounded, chart-based reading</div>" in html_subtitle)
check("A: no subtitle element when not supplied", "cover-subtitle" not in body_of(render(report_subtitle=None)))

html_sample = render(is_sample=True)
check("A: SAMPLE marker renders when requested", "<div class=\"cover-sample-badge\">Sample Report</div>" in html_sample)
check("A: no SAMPLE marker when not requested", "cover-sample-badge" not in body_of(render(is_sample=False)))

# Q2.1 locked rule: the cover contains NOTHING else, even when every
# other component is populated.
html_everything = render(
    answer_hero={"label": "L", "value": "V"},
    result_cards=[{"label": "L", "value": "V"}],
    fact_cards=[{"heading": "H", "text": "T"}],
    gemstone={"gemstone": "Ruby", "planet": "Sun"},
    app_download={"heading": "Get App"},
)
cover_html = cover_of(html_everything)
check("A: cover contains NO answer-hero even when one is supplied", "answer-hero" not in cover_html)
check("A: cover contains NO result-card/fact-card even when supplied", "result-card" not in cover_html and "fact-card" not in cover_html)
check("A: cover contains NO gemstone box even when supplied", "gemstone-box" not in cover_html)
check("A: cover contains NO app-download box even when supplied", "app-download-box" not in cover_html)

# =================================================================
print("\n=== B: Page-2 Primary Answer Hero (Q2.1) ===")
# =================================================================
check("B: no answer-hero element by default (legacy compatibility)", "answer-hero" not in body_of(render(answer_hero=None)))

hero_html = render(answer_hero={
    "label": "Startup Outlook", "value": "FAVORABLE",
    "interpretation": "The current window supports calculated action.",
    "evidence": ["2nd/7th/10th houses show supportive lordship", "Current Dasha favors initiative"],
    "timing": "Now through mid-2028", "caution": "Cash-flow discipline still matters.",
})
b = body_of(hero_html)
check("B: hero renders label/value/interpretation", "Startup Outlook" in b and "FAVORABLE" in b and "The current window supports calculated action." in b)
check("B: hero renders evidence points as a list", "2nd/7th/10th houses show supportive lordship" in b and "Current Dasha favors initiative" in b)
check("B: hero renders optional timing and caution", "Now through mid-2028" in b and "Cash-flow discipline still matters." in b)

# The critical product rule: hero must appear BEFORE the Kundali snapshot.
hero_and_chart_html = render(
    answer_hero={"label": "L", "value": "V"},
    kundali_img_src="tmp/fake.svg",
)
hero_pos = hero_and_chart_html.find("answer-hero")
snapshot_pos = hero_and_chart_html.find("snapshot-kundali")
check("B: answer hero renders BEFORE the Kundali snapshot in document order", 0 <= hero_pos < snapshot_pos)

# Absence must never break legacy calls (no hero param at all == None).
try:
    out_path = os.path.join(os.environ.get("TEMP", "."), "q21_no_hero_test.pdf")
    generate_pdf_report_weasy(
        output_path=out_path,
        user_info={"name": "T", "dob": "1990-06-15", "tob": "10:30", "pob": "Delhi"},
        summary_blocks={"birth_chart_summary": "X"}, gpt_response="Text.",
        kundali_drawing=generate_kundali_drawing(planets=PLANETS, lagna_rashi=5),
        used_placeholders=["birth_chart_summary"], product="startup_suggestion_report",
    )
    check("B: omitting answer_hero entirely (legacy call) succeeds with no crash", os.path.exists(out_path))
    os.remove(out_path)
except Exception as exc:
    check(f"B: omitting answer_hero entirely (legacy call) succeeds with no crash ({exc})", False)

# =================================================================
print("\n=== C: App-download-only closing CTA (Q2.1) ===")
# =================================================================
check("C: no app-download element by default", "app-download-box" not in body_of(render(app_download=None)))
check("C: the removed generic 'cta' template variable is gone from the template source entirely",
      "{% if cta %}" not in open("templates/report_template.html", encoding="utf-8").read())
check("C: no consultation-style copy exists anywhere in the template source",
      "deeper 1:1 consultation" not in open("templates/report_template.html", encoding="utf-8").read()
      and "Talk to an astrologer" not in open("templates/report_template.html", encoding="utf-8").read())

app_html = render(app_download={"heading": "Discover more with the app", "benefit_text": "Daily personalized insights."})
b = body_of(app_html)
check("C: app-download renders heading/benefit text", "Discover more with the app" in b and "Daily personalized insights." in b)
# Q3 Batch 1 (human visual QA correction) -- exact CTA copy updated to
# "Download Jyotishasha App" (was "Download the Jyotishasha App");
# still the one locked action, still app-download only.
check("C: app-download always states the one locked action", "Download Jyotishasha App" in b)

app_with_urls = render(app_download={"play_store_url": "https://play.google.com/store/apps/details?id=com.jyotishasha.app"})
check("C: optional Play Store URL renders when supplied", "play.google.com/store/apps/details?id=com.jyotishasha.app" in body_of(app_with_urls))

app_no_urls = render(app_download={"heading": "Get the App"})
b = body_of(app_no_urls)
check("C: NO fake/invented store link appears when URLs are not supplied", "play.google.com" not in b and "apps.apple.com" not in b)

# generate_pdf_report_weasy() no longer accepts `cta` as a parameter at all.
import inspect
sig = inspect.signature(generate_pdf_report_weasy)
check("C: generate_pdf_report_weasy() no longer has a generic 'cta' parameter", "cta" not in sig.parameters)
check("C: generate_pdf_report_weasy() has the new 'app_download' parameter", "app_download" in sig.parameters)

# =================================================================
print("\n=== D: Disclaimer slot ===")
# =================================================================
check("D: no disclaimer element by default", "<div class=\"disclaimer-box\">" not in body_of(render(disclaimer=None)))
check("D: disclaimer renders when supplied", "This is astrology-based guidance, not financial advice." in body_of(render(disclaimer="This is astrology-based guidance, not financial advice.")))

# =================================================================
print("\n=== E: Reusable component system ===")
# =================================================================
html_result = render(result_cards=[{"label": "Outlook", "value": "Favorable", "detail": "Strong current window"}])
b = body_of(html_result)
check("E: result card renders", "<div class=\"result-card\">" in b and "Favorable" in b)
check("E: no result card when list is empty", "<div class=\"result-card\">" not in body_of(render(result_cards=[])))

html_fact = render(fact_cards=[{"heading": "10th House — Career & Public Standing", "items": ["Sign: Leo", "Lord: Sun", "Lord placed in: 1st House (Leo)", "Occupying planets: none"]}])
b = body_of(html_fact)
check("E: fact card supports the consumer-friendly empty-house hierarchy (sign/lord/lord-placement first, occupancy last)",
      "Sign: Leo" in b and "Lord: Sun" in b and "Lord placed in: 1st House (Leo)" in b and "Occupying planets: none" in b)

html_timeline = render(timeline={"heading": "Dasha Window", "entries": [{"label": "Saturn - Jupiter", "date_range": "2025 to 2028", "current": True}]})
check("E: timeline renders", "Dasha Window" in body_of(html_timeline) and "Saturn - Jupiter" in body_of(html_timeline))
check("E: no timeline block when entries empty", "timeline-block" not in body_of(render(timeline={"heading": "X", "entries": []})))

html_table = render(tables=[{"heading": "House-Lord Snapshot", "headers": ["House", "Lord"], "rows": [["7th", "Saturn"]]}])
check("E: table renders", "House-Lord Snapshot" in body_of(html_table) and "<td>Saturn</td>" in body_of(html_table))
check("E: no table when list is empty", "data-table" not in body_of(render(tables=[])))

html_notice = render(notices=[{"heading": "Please Note", "text": "Not a substitute for legal advice."}])
check("E: notice box renders", "notice-box" in body_of(html_notice) and "Please Note" in body_of(html_notice))
check("E: no notice box when list is empty", "notice-box" not in body_of(render(notices=[])))

html_highlight = render(highlights=[{"heading": "Key Guidance", "text": "Act during the current window."}])
check("E: highlight box renders", "highlight-box" in body_of(html_highlight))
check("E: no highlight box when list is empty", "highlight-box" not in body_of(render(highlights=[])))

# Q2.1 -- numbered action/guidance list.
html_action = render(action_list={"heading": "Next Steps", "items": ["Organize documents", "Set a review date"]})
b = body_of(html_action)
check("E: numbered action list renders as an ordered list, distinct markup from a fact-card bullet list",
      "action-list" in b and "Organize documents" in b and "Set a review date" in b)
check("E: no action-list block when items empty", "action-list-block" not in body_of(render(action_list={"heading": "X", "items": []})))
check("E: no action-list block when action_list is None", "action-list-block" not in body_of(render(action_list=None)))

# Q2.1 -- gemstone recommendation, LOCKED rule: concrete data only.
check("E: no gemstone box by default", "gemstone-box" not in body_of(render(gemstone=None)))
gem_html = render(gemstone={"planet": "Jupiter", "gemstone": "Yellow Sapphire", "substone": "Citrine", "reason": "Jupiter is the strongest benefic in this chart.", "caution": "Consult before wearing."})
b = body_of(gem_html)
check("E: gemstone box renders concrete data", "Yellow Sapphire" in b and "Citrine" in b and "Jupiter" in b and "Jupiter is the strongest benefic in this chart." in b and "Consult before wearing." in b)
check("E: no gemstone box when the dict has neither a gemstone nor a planet (degenerate/empty data)", "gemstone-box" not in body_of(render(gemstone={"reason": "some text but no concrete recommendation"})))
import re as _re
_raw_source = open("templates/report_template.html", encoding="utf-8").read()
_source_no_comments = _re.sub(r"<!--.*?-->", "", _raw_source, flags=_re.DOTALL)
check("E: NO generic gemstone filler copy is ever RENDERED (checked outside explanatory HTML comments, which legitimately document the anti-pattern by name)",
      "supportive gemstone" not in _source_no_comments.lower())

# All components together through real WeasyPrint (no crash).
html_all = render(
    report_subtitle="Sub", is_sample=True,
    answer_hero={"label": "L", "value": "V", "evidence": ["E1"]},
    result_cards=[{"label": "L", "value": "V"}],
    fact_cards=[{"heading": "H", "items": ["I1"]}],
    timeline={"heading": "TL", "entries": [{"label": "E1", "current": True}]},
    tables=[{"heading": "TB", "headers": ["A"], "rows": [["1"]]}],
    action_list={"heading": "AL", "items": ["Step 1"]},
    notices=[{"heading": "N", "text": "NT"}],
    highlights=[{"heading": "HL", "text": "HT"}],
    gemstone={"gemstone": "Ruby", "planet": "Sun"},
    disclaimer="Disc.",
    app_download={"heading": "App", "play_store_url": "https://play.google.com/store/apps/details?id=com.jyotishasha.app"},
)
try:
    HTML(string=html_all, base_url=BASE_DIR).render()
    check("E: a report using ALL Q2/Q2.1 components together renders through real WeasyPrint with no exception", True)
except Exception as exc:
    check(f"E: a report using ALL Q2/Q2.1 components together renders through real WeasyPrint with no exception ({exc})", False)

# =================================================================
print("\n=== F: Relationship pipeline compatibility ===")
# =================================================================
love_html = render(
    report_title="Relationship Future Report",
    birth_chart_summary="", mahadasha_summary="", current_transit_summary="",
    gpt_response_html=convert_headings("# Relationship Future Report\n\n## Overall Direction & Potential\nGrounded foundation.\n\n@@Varna: A supportive alignment.\n"),
)
check("F: relationship shape renders with no crash and no standard-only fact-card leaks in", "fact-card" not in body_of(love_html))
check("F: relationship's own # heading becomes a real H1", "<h1 class='section-heading'>Relationship Future Report</h1>" in love_html)
check("F: relationship's own ## heading becomes a real H2", "<h2 class='section-heading'>Overall Direction & Potential</h2>" in love_html)
check("F: relationship's own @@Label: syntax still renders as inline emphasis, not a heading", "<strong>Varna:</strong> A supportive alignment." in love_html)

try:
    out_path = os.path.join(os.environ.get("TEMP", "."), "q21_love_shape_test.pdf")
    generate_pdf_report_weasy(
        output_path=out_path,
        user_info={"name": "Love Test", "dob": "1992-01-01", "tob": "10:00", "pob": "Mumbai"},
        summary_blocks={}, gpt_response="# Relationship Future Report\n\n## Overall Direction & Potential\nText.\n",
        kundali_drawing=generate_kundali_drawing(planets=PLANETS, lagna_rashi=5),
        used_placeholders=[], product="relationship_future_report", language="en",
    )
    check("F: generate_pdf_report_weasy() with the EXACT real love_premium_task.py call shape succeeds", os.path.exists(out_path))
    os.remove(out_path)
except Exception as exc:
    check(f"F: generate_pdf_report_weasy() with the EXACT real love_premium_task.py call shape succeeds ({exc})", False)

# =================================================================
print("\n=== G: Hindi/Unicode ===")
# =================================================================
hindi_html = render(is_hindi=True, lang="hi", gpt_response_html=convert_headings("**करियर अभिविन्यास**\nसामग्री यहाँ है।"))
check("G: body carries the hi class when Hindi is requested", 'class="hi"' in hindi_html)
check("G: Devanagari whole-line bold becomes a real H2 heading", "करियर अभिविन्यास</h2>" in hindi_html)
english_html = render(is_hindi=False, lang="en")
check("G: body does NOT carry the hi class for English", "<body class=\"\">" in english_html)

# =================================================================
print("\n=== H: convert_headings() -- heading hierarchy + Q2.1 bullet fix ===")
# =================================================================
check("H: a whole-line **Heading** becomes a real <h2>", "<h2 class='section-heading'>Business Orientation</h2>" in convert_headings("**Business Orientation**\nBody text."))
check("H: inline **bold** mid-sentence is still just emphasis", "<p>This is <strong>important</strong> mid sentence.</p>" in convert_headings("This is **important** mid sentence."))
check("H: relationship's own # H1 convention is unaffected", "<h1 class='section-heading'>Main</h1>" in convert_headings("# Main\nBody."))
check("H: relationship's own ## H2 convention is unaffected", "<h2 class='section-heading'>Sub</h2>" in convert_headings("## Sub\nBody."))
check("H: relationship's own @@Label: convention is unaffected", "<p><strong>Varna:</strong> text</p>" in convert_headings("@@Varna: text"))
check("H: cards do not hardcode the 'hi' class", "<div class='card'>" in convert_headings("Plain paragraph.") and "card hi" not in convert_headings("Plain paragraph."))

# Q2.1 -- the exact reported artifact: bare bullet markers with no
# content, immediately before a real heading.
empty_bullets_text = "-\n-\n-\n\n**Business Orientation**\nReal content."
converted = convert_headings(empty_bullets_text)
check("H: bare '-' marker lines with no content render NOTHING (no empty <li>, no stray <p>-</p>)",
      "<li></li>" not in converted and "<p>-</p>" not in converted)
check("H: the real heading that follows the stray markers still renders correctly", "<h2 class='section-heading'>Business Orientation</h2>" in converted)

for marker in ("-", "*", "•"):
    stray = f"{marker}\n{marker}   \n\nReal paragraph."
    result = convert_headings(stray)
    check(f"H: bare {marker!r} marker lines (with/without trailing whitespace) produce no empty list item",
          "<li></li>" not in result and f"<p>{marker}</p>" not in result)

# Real bullet content becomes a genuine <ul><li>, not a flat paragraph.
real_bullets = convert_headings("- First point\n- Second point with **bold**\n- Third point")
check("H: real bullet lines become a genuine <ul class='body-list'> with real <li> items",
      "<ul class='body-list'>" in real_bullets and "<li>First point</li>" in real_bullets
      and "<li>Second point with <strong>bold</strong></li>" in real_bullets)
check("H: real bullet content is no longer flattened into '<p>- text</p>' paragraphs",
      "<p>- First point</p>" not in real_bullets)

# narrative_style="plain" skips the card shell entirely.
plain = convert_headings("**Heading**\nBody paragraph.", narrative_style="plain")
check("H: narrative_style='plain' renders the heading but no card shell", "<h2 class='section-heading'>Heading</h2>" in plain and "<div class='card'>" not in plain)
default_style = convert_headings("**Heading**\nBody paragraph.")
check("H: default narrative_style is unchanged ('card') -- legacy callers see identical output to before", "<div class='card'>" in default_style)

# =================================================================
print("\n=== I: Page-flow structure ===")
# =================================================================
template_source = open("templates/report_template.html", encoding="utf-8").read()
check("I: exactly ONE unconditional page-break-after:always (the cover)", template_source.count("page-break-after: always") == 1)
check("I: no standalone forced-break DOM element between snapshot and body", '<div style="page-break-after: always;"></div>' not in template_source)
check("I: cards/result-cards/fact-cards/notices/highlights/gemstone/action-list all use page-break-inside:avoid",
      template_source.count("page-break-inside: avoid") >= 8)

# =================================================================
print("\n=== J: Footer / page numbering ===")
# =================================================================
check("J: real CSS Paged Media page-numbering rule present", "counter(page)" in template_source and "counter(pages)" in template_source)
check("J: page-numbering lives inside @page's own margin box", "@bottom-center" in template_source.split("</style>", 1)[0])

# =================================================================
print("\n=== K: A4 sizing (real WeasyPrint render) ===")
# =================================================================
for name, html_to_check in (("standard", render()), ("with-hero", hero_html), ("relationship-shape", love_html), ("hindi", hindi_html)):
    try:
        doc = HTML(string=html_to_check, base_url=BASE_DIR).render()
        width_mm = doc.pages[0].width / 96 * 25.4
        height_mm = doc.pages[0].height / 96 * 25.4
        check(f"K: {name} scenario renders to real A4 (210x297mm), got ({width_mm:.1f}x{height_mm:.1f}mm)",
              abs(width_mm - 210.0) < 0.5 and abs(height_mm - 297.0) < 0.5)
    except Exception as exc:
        check(f"K: {name} scenario renders to real A4 ({exc})", False)

# =================================================================
print("\n=== L: Existing/legacy generation compatibility ===")
# =================================================================
try:
    out_path = os.path.join(os.environ.get("TEMP", "."), "q21_legacy_shape_test.pdf")
    generate_pdf_report_weasy(
        output_path=out_path,
        user_info={"name": "Std Test", "dob": "1990-06-15", "tob": "10:30", "pob": "Delhi"},
        summary_blocks={
            "birth_chart_summary": "You have a Leo Ascendant.",
            "mahadasha_summary": "You are in Saturn Mahadasha.",
            "current_transit_summary": "Saturn is in Pisces.",
        },
        gpt_response="**Business Orientation**\nText here.\n\n**Summary**\nMore text.",
        kundali_drawing=generate_kundali_drawing(planets=PLANETS, lagna_rashi=5),
        used_placeholders=["birth_chart_summary", "mahadasha_summary", "current_transit_summary"],
        product="startup_suggestion_report",
        # Deliberately the EXACT pre-Q2 call shape: no language=, no
        # component of any kind.
    )
    check("L: generate_pdf_report_weasy() with the pre-Q2 call shape still succeeds", os.path.exists(out_path))
    os.remove(out_path)
except Exception as exc:
    check(f"L: generate_pdf_report_weasy() with the pre-Q2 call shape still succeeds ({exc})", False)

print("\n" + "=" * 50)
print(f"TOTAL: {passed} passed, {failed} failed")
print("=" * 50)

if failed:
    sys.exit(1)
