# test_report_hindi_static_labels.py

"""
Q4.2A -- Modern Conversational Hindi policy: permanent regression guards.

Covers only the deterministic pieces (no AI, no DB, no network):
  1. every static label exists for en+hi; English values are EXACTLY the
     strings the template used to hardcode (English output unchanged);
  2. the template no longer hardcodes those strings;
  3. rendered HTML: English keeps its old markup, Hindi gets localized
     labels and no leftover English cover/summary labels;
  4. Hindi Birth Chart Summary display keeps every planet/house/sign fact;
  5. page-flow CSS fix is scoped to body.hi (English pagination untouched);
  6. career_report_hi.txt keeps its structural contract and carries the
     modern-Hindi policy markers.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DATABASE_URL", "postgresql://sample:unused@localhost:5432/jyotishasha_local")
os.environ.setdefault("ACTIVITY_EVENTS_ENVIRONMENT", "local")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

passed = 0
failed = 0


def check(label, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


ROOT = os.path.dirname(os.path.abspath(__file__))
from modules.payments.report_i18n_labels import LABELS, get_label, labels_for_language  # noqa: E402
from summary_blocks import build_birth_chart_summary_display  # noqa: E402
import pdf_generator_weasy as pg  # noqa: E402

template_src = open(os.path.join(ROOT, "templates", "report_template.html"), encoding="utf-8").read()

print("\n=== 1: labels -- en unchanged, hi present ===")
OLD_EN = {
    "sample_badge": "Sample Report",
    "prepared_for": "Prepared for:",
    "report_date": "Report Date:",
    "birth_chart_summary_heading": "Birth Chart Summary",
    "mahadasha_summary_heading": "Mahadasha Summary",
    "current_transit_summary_heading": "Current Transit Summary",
    "chart_legend": "Su = Sun &nbsp; Mo = Moon &nbsp; Ma = Mars &nbsp; Me = Mercury &nbsp; Ju = Jupiter &nbsp; Ve = Venus &nbsp; Sa = Saturn &nbsp; Ra = Rahu &nbsp; Ke = Ketu",
}
for key, old in OLD_EN.items():
    check(f"1: en label '{key}' equals the previously hardcoded English string", get_label(key, "en") == old)
check("1: every label key has non-empty en AND hi", all(v.get("en") and v.get("hi") for v in LABELS.values()))
check("1: hi sample badge is 'नमूना रिपोर्ट'", get_label("sample_badge", "hi") == "नमूना रिपोर्ट")
check("1: hi labels differ from en for every new cover/summary key",
      all(get_label(k, "hi") != get_label(k, "en") for k in OLD_EN))
check("1: unknown language still falls back to English", get_label("sample_badge", "fr") == "Sample Report")

print("\n=== 2: template no longer hardcodes those strings ===")
for lit in ("Prepared for:</strong>", "Report Date:</strong>", ">Sample Report<", ">Birth Chart Summary<",
            ">Mahadasha Summary<", ">Current Transit Summary<", "Su = Sun &nbsp;"):
    check(f"2: template has no hardcoded '{lit}'", lit not in template_src)

print("\n=== 3: rendered HTML (en vs hi) ===")
captured = {}


class _FakeHTML:
    def __init__(self, string=None, base_url=None):
        captured["html"] = string

    def write_pdf(self, path):
        pass


from types import SimpleNamespace  # noqa: E402
from reportlab.graphics.shapes import Drawing  # noqa: E402

_real_html = pg.HTML
_real_svg = pg.renderSVG
pg.HTML = _FakeHTML
pg.renderSVG = SimpleNamespace(drawToFile=lambda *a, **k: None)  # a chart image must exist for the legend to render; no file is written
try:
    def render(lang, summary):
        pg.generate_pdf_report_weasy(
            output_path=os.path.join(ROOT, "tmp", "_q42a_unused.pdf"),
            user_info={"name": "Test Person", "dob": "1990-06-15", "tob": "14:30", "pob": "Lucknow"},
            summary_blocks={"birth_chart_summary": summary}, gpt_response="**1. H**\nText.",
            kundali_drawing=Drawing(10, 10), used_placeholders=["birth_chart_summary"], product="career_report",
            language=lang, is_sample=True)
        return captured["html"]

    en_html = render("en", "You have a Libra Ascendant.")
    hi_html = render("hi", "आपका Lagna Libra है।")
finally:
    pg.HTML = _real_html
    pg.renderSVG = _real_svg

check("3: en keeps '<div class=\"cover-sample-badge\">Sample Report</div>'", '<div class="cover-sample-badge">Sample Report</div>' in en_html)
check("3: en keeps 'Prepared for:' / 'Report Date:' / 'Birth Chart Summary'",
      "<strong>Prepared for:</strong>" in en_html and "<strong>Report Date:</strong>" in en_html and ">Birth Chart Summary<" in en_html)
check("3: en legend keeps '&nbsp;' separators", "Su = Sun &nbsp; Mo = Moon" in en_html)
check("3: hi shows 'नमूना रिपोर्ट' badge", '<div class="cover-sample-badge">नमूना रिपोर्ट</div>' in hi_html)
check("3: hi shows localized name/date labels", "<strong>नाम:</strong>" in hi_html and "<strong>Report की तारीख:</strong>" in hi_html)
check("3: hi shows localized summary heading + bilingual legend",
      "आपकी Birth Chart का Summary" in hi_html and "Sun (Surya)" in hi_html)
check("3: hi HTML has no leftover English cover/summary labels",
      not any(x in hi_html[hi_html.index("<body"):] for x in ("Prepared for:", ">Birth Chart Summary<", ">Sample Report<")))

print("\n=== 4: Hindi Birth Chart Summary display keeps every fact ===")
kundali = {
    "lagna_sign": "Libra",
    "planets": [
        {"name": "Ascendant (Lagna)", "house": 1, "sign": "Libra"},
        {"name": "Saturn", "house": 4, "sign": "Capricorn"},
        {"name": "Moon", "house": 5, "sign": "Aquarius"},
        {"name": "Rahu", "house": 4, "sign": "Capricorn"},
        {"name": "Mercury", "house": 11, "sign": "Taurus"},
        {"name": "Sun", "house": 12, "sign": "Gemini"},
        {"name": "Venus", "house": 2, "sign": "Aries"},
    ],
}
en_summary = "You have a Libra Ascendant. Saturn is placed in 4th house (Capricorn)."
check("4: non-Hindi languages get the English summary back unchanged",
      build_birth_chart_summary_display(kundali, "en", en_summary) == en_summary)
hi_summary = build_birth_chart_summary_display(kundali, "hi", en_summary)
check("4: hi summary names the Lagna sign", "Lagna Libra" in hi_summary)
for p in kundali["planets"]:
    if "Ascendant" in p["name"]:
        continue
    n = p["house"]
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    check(f"4: hi summary keeps {p['name']} -> {n}{suffix} House ({p['sign']})",
          p["name"] in hi_summary and f"{n}{suffix} House" in hi_summary and f"({p['sign']} राशि)" in hi_summary)
check("4: hi summary uses bilingual planet names (Saturn (Shani), Moon (Chandra))",
      "Saturn (Shani)" in hi_summary and "Moon (Chandra)" in hi_summary)
check("4: hi summary contains no Ascendant row", "Ascendant" not in hi_summary)

print("\n=== 5: page-flow CSS is Hindi-scoped ===")
check("5: English/shared .card still uses page-break-inside: avoid",
      re.search(r"\n\s*\.card \{[^}]*page-break-inside: avoid;", template_src) is not None)
check("5: Hindi-only override 'body.hi .card { page-break-inside: auto; }' present",
      "body.hi .card { page-break-inside: auto; }" in template_src)
check("5: Hindi badge override is body.hi scoped", "body.hi .cover-sample-badge" in template_src)

print("\n=== 6: career_report_hi.txt contract + policy markers ===")
hi_prompt = open(os.path.join(ROOT, "prompts", "career_report_hi.txt"), encoding="utf-8").read()
check("6: 9 numbered section headings", len(re.findall(r"^\*\*\d+\. ", hi_prompt, re.MULTILINE)) == 9)
check("6: no Latin-lettered whole-line-bold heading", not [l for l in hi_prompt.splitlines() if re.match(r"^\*\*[A-Za-z]", l.strip())])
check("6: all 4 context placeholders present",
      all(f"{{{k}}}" in hi_prompt for k in ("birth_chart_summary", "house_lord_summary", "career_yoga_summary", "dasha_window_summary")))
check("6: empty-house rule preserved", "इस भाव में कोई ग्रह नहीं है इसलिए विश्लेषण संभव नहीं" in hi_prompt)
check("6: META/REPORT markers preserved", "===META===" in hi_prompt and "===REPORT===" in hi_prompt)
check("6: template .format() works with the 4 blocks",
      bool(hi_prompt.format(birth_chart_summary="a", house_lord_summary="b", career_yoga_summary="c", dasha_window_summary="d")))
check("6: policy states modern conversational Hindi + bans Sanskritized/academic Hindi",
      "Modern Conversational Hindi" in hi_prompt and "संस्कृतनिष्ठ" in hi_prompt and "academic" in hi_prompt)
check("6: policy keeps familiar modern terms in English", all(w in hi_prompt for w in ("Career", "Opportunity", "Planning", "Communication")))
check("6: policy gives bilingual planet names", all(w in hi_prompt for w in ("Sun (Surya)", "Moon (Chandra)", "Saturn (Shani)", "Mercury (Budh)")))
check("6: policy shows the BAD/GOOD example for the 10th House Lord", "आपके 10th House का Lord Moon है" in hi_prompt)
check("6: policy requires dates copied exactly as given (no numeric reformatting; the retired DD/MM/YYYY contract is gone)",
      "बिल्कुल वैसे ही (exactly as given) लिखें" in hi_prompt and "DD/MM/YYYY" not in hi_prompt)
check("6: no-guarantee rule preserved", "गारंटी कभी न दें" in hi_prompt)

print("\n=== 7: Q4.2B -- modern-Hindi policy rolled out to all 23 remaining standard_v1 prompts ===")
from modules.payments.report_product_intelligence import REGISTRY  # noqa: E402

# (heading count, placeholders, META top-level keys) captured from the pre-Q4.2B prompts --
# the rollout must change LANGUAGE only, never the structured-output contract.
_STD_CONTRACT = {
    "business_report": (9, ('birth_chart_summary', 'career_yoga_summary', 'dasha_window_summary', 'house_lord_summary', 'wealth_yoga_summary'), ('action_items', 'answer_hero', 'gemstone_reason')),
    "children_parenting_report": (9, ('birth_chart_summary', 'dasha_window_summary', 'house_lord_summary'), ('action_items', 'answer_hero', 'gemstone_reason')),
    "delay_in_marriage_report": (6, ('birth_chart_summary', 'dasha_window_summary', 'house_lord_summary', 'targeted_aspect_summary'), ('action_items', 'answer_hero', 'gemstone_reason')),
    "divorce_possibility_report": (10, ('birth_chart_summary', 'dasha_window_summary', 'house_lord_summary', 'targeted_aspect_summary'), ('action_items', 'answer_hero', 'gemstone_reason')),
    "financial_report": (8, ('birth_chart_summary', 'dasha_window_summary', 'house_lord_summary', 'wealth_yoga_summary'), ('action_items', 'answer_hero', 'gemstone_reason')),
    "financial_stability_report": (8, ('birth_chart_summary', 'dasha_window_summary', 'house_lord_summary', 'wealth_yoga_summary'), ('action_items', 'answer_hero', 'gemstone_reason')),
    "foreign_travel_report": (9, ('birth_chart_summary', 'dasha_window_summary', 'foreign_travel_summary'), ('action_items', 'answer_hero')),
    "gemstone_consultation": (9, ('birth_chart_summary', 'dasha_window_summary', 'gemstone_summary', 'house_lord_summary'), ('action_items', 'answer_hero', 'gemstone_reason')),
    "government_job_report": (8, ('birth_chart_summary', 'career_yoga_summary', 'dasha_window_summary', 'house_lord_summary'), ('action_items', 'answer_hero', 'gemstone_reason')),
    "jupiter_transit_report": (9, ('birth_chart_summary', 'house_lord_summary', 'transit_facts_summary'), ('action_items', 'answer_hero')),
    "legal_disputes_report": (9, ('birth_chart_summary', 'dasha_window_summary', 'house_lord_summary'), ('action_items', 'answer_hero', 'gemstone_reason')),
    "lifestyle_analysis_report": (9, ('birth_chart_summary', 'dasha_window_summary', 'house_lord_summary'), ('action_items', 'answer_hero', 'gemstone_reason')),
    "love_disappointment_report": (9, ('birth_chart_summary', 'dasha_window_summary', 'house_lord_summary', 'targeted_aspect_summary'), ('action_items', 'answer_hero')),
    "love_marriage_report": (8, ('birth_chart_summary', 'dasha_window_summary', 'gemstone_summary', 'house_lord_summary', 'targeted_aspect_summary'), ('action_items', 'answer_hero', 'gemstone_reason')),
    "love_relationship_report": (9, ('birth_chart_summary', 'dasha_window_summary', 'gemstone_summary', 'house_lord_summary'), ('action_items', 'answer_hero', 'gemstone_reason')),
    "marriage_report": (8, ('birth_chart_summary', 'dasha_window_summary', 'house_lord_summary', 'manglik_summary', 'targeted_aspect_summary'), ('action_items', 'answer_hero', 'gemstone_reason')),
    "mood_mental_health_report": (10, ('birth_chart_summary', 'dasha_window_summary', 'house_lord_summary'), ('action_items', 'answer_hero', 'gemstone_reason')),
    "problem_in_marriage_report": (8, ('birth_chart_summary', 'dasha_window_summary', 'house_lord_summary', 'targeted_aspect_summary'), ('action_items', 'answer_hero')),
    "property_report": (9, ('birth_chart_summary', 'dasha_window_summary', 'house_lord_summary'), ('action_items', 'answer_hero', 'gemstone_reason')),
    "sadhesati_report": (9, ('birth_chart_summary', 'dasha_window_summary', 'sadhesati_summary'), ('action_items', 'answer_hero')),
    "saturn_transit_report": (12, ('birth_chart_summary', 'house_lord_summary', 'sadhesati_summary', 'transit_facts_summary'), ('action_items', 'answer_hero')),
    "second_marriage_report": (6, ('birth_chart_summary', 'dasha_window_summary', 'house_lord_summary'), ('action_items', 'answer_hero')),
    "startup_suggestion_report": (8, ('birth_chart_summary', 'career_yoga_summary', 'dasha_window_summary', 'house_lord_summary', 'wealth_yoga_summary'), ('action_items', 'answer_hero', 'gemstone_reason')),
}
import json as _json  # noqa: E402

_std_slugs = sorted(sl for sl, pr in REGISTRY.items() if pr.generator == "standard_v1")
check("7: registry has exactly 24 standard_v1 products (career_report + the 23 rolled out)", len(_std_slugs) == 24)
check("7: the 23 contract entries are exactly the registry's standard_v1 products minus career_report",
      sorted(_STD_CONTRACT) == sorted(sl for sl in _std_slugs if sl != "career_report"))

_POLICY_INVARIANT = ("Modern Conversational Hindi", "क्लिष्ट, संस्कृतनिष्ठ, academic", "बिल्कुल वैसे ही (exactly as given) लिखें",
                     "Sun (Surya), Moon (Chandra), Mars (Mangal), Mercury (Budh), Jupiter (Guru), Venus (Shukra), Saturn (Shani), Rahu, Ketu")
for slug in _std_slugs:
    text = open(os.path.join(ROOT, "prompts", f"{slug}_hi.txt"), encoding="utf-8").read()
    check(f"7: {slug}_hi.txt carries the modern-Hindi policy block", all(m in text for m in _POLICY_INVARIANT))
    if slug == "career_report":
        continue
    n_heads, phs, meta_top = _STD_CONTRACT[slug]
    found_ph = tuple(sorted(set(re.findall(r"(?<!{){([a-z_]+)}(?!})", text))))
    check(f"7: {slug}_hi.txt placeholders unchanged", found_ph == phs)
    check(f"7: {slug}_hi.txt has {n_heads} numbered headings, in order",
          re.findall(r"^\*\*(\d+)\.", text, re.MULTILINE) == [str(i) for i in range(1, n_heads + 1)])
    formatted = text.format(**{k: "X" for k in phs})
    m = re.search(r"===META===\s*(\{.*?\})\s*===REPORT===", formatted, re.S)
    try:
        meta = _json.loads(m.group(1))
        shape_ok = tuple(sorted(meta)) == meta_top and sorted(meta["answer_hero"]) == ["evidence", "interpretation", "label", "value"]
    except Exception:
        shape_ok = False
    check(f"7: {slug}_hi.txt META JSON keys unchanged", shape_ok)
    check(f"7: {slug}_hi.txt keeps ===META===/===REPORT=== markers", "===META===" in text and "===REPORT===" in text)
    check(f"7: {slug}_hi.txt has no Latin-lettered whole-line-bold heading",
          not [l for l in text.splitlines() if re.match(r"^\*\*[A-Za-z]", l.strip())])
    if slug != "saturn_transit_report":  # its original prompt has no outcome-guarantee rule (only anti-fabrication rules); none was added
        check(f"7: {slug}_hi.txt keeps an explicit no-guarantee / non-prediction safety rule",
              any(w in text for w in ("गारंटी", "पक्की बात", "भविष्यवाणी", "वादा", "दावा या इशारा")))

_flagged = ("अभिविन्यास", "प्रवृत्तियाँ", "व्यावसायिक", "यथार्थवादी")
_structure_parts = {}
for sl in _STD_CONTRACT:
    t = open(os.path.join(ROOT, "prompts", f"{sl}_hi.txt"), encoding="utf-8").read()
    _structure_parts[sl] = t.split("Report -- सख्त Section Structure")[-1] if "Report -- सख्त Section Structure" in t else t.split("इन numbered sections में पूरी report लिखें:")[-1]
check("7: rewritten Hindi section headings/instructions no longer use the flagged Sanskritized words",
      [sl for sl, part in _structure_parts.items() if any(w in part for w in _flagged)] == [])
check("7: relationship_future_report_hi.txt (dedicated dual-person pipeline) was NOT touched by the rollout",
      "Modern Conversational Hindi" not in open(os.path.join(ROOT, "prompts", "relationship_future_report_hi.txt"), encoding="utf-8").read())
_ld = open(os.path.join(ROOT, "prompts", "love_disappointment_report_hi.txt"), encoding="utf-8").read()
check("7: love_disappointment_report_hi.txt still has no gemstone wording", "gemstone" not in _ld.lower() and "रत्न" not in _ld)

print("\n=== 8: Q4.2B -- shared timeline-note labels (Saturn/Jupiter Transit, Sade Sati) ===")
check("8: en 'current_transit_note' equals the previously hardcoded English note", get_label("current_transit_note", "en") == "Current transit sign residency")
check("8: en 'current_sadhesati_phase_note' equals the previously hardcoded English note", get_label("current_sadhesati_phase_note", "en") == "Current Sade Sati phase")
check("8: hi notes are localized", get_label("current_transit_note", "hi") == "अभी का Transit" and get_label("current_sadhesati_phase_note", "hi") == "अभी चल रहा Phase")
_b1 = open(os.path.join(ROOT, "modules", "payments", "report_q3_batch1.py"), encoding="utf-8").read()
_b5 = open(os.path.join(ROOT, "modules", "payments", "report_q3_batch5.py"), encoding="utf-8").read()
check("8: builders no longer hardcode the English notes",
      '"Current transit sign residency"' not in _b1 + _b5 and 'entry_note = "Current Sade Sati phase"' not in _b5)

print("\n" + "=" * 60)
print(f"TOTAL: {passed} passed, {failed} failed")
print("=" * 60)
sys.exit(1 if failed else 0)
