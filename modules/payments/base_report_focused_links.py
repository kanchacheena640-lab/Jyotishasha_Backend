"""Optional Rs51 Focused Reports suggested at the end of each Base (standard) Report PDF.

A simple static mapping, 0-3 focused question keys per base report, chosen for what a reader of that report may
genuinely want to ask next. A slot is left empty rather than filled with a generic, repeated, fear-led or mismatched
topic, so some base reports list fewer than three and some none (the PDF then omits the block). Titles come from the
focused prompt specs (the same product titles the focused pages and PDFs use) and URLs are the live focused pages,
EN or /hi/ to match the PDF. Two-person focused reports are flagged so the PDF can say partner details are needed.
"""
from modules.focused_reports.prompt_assembler import language_key
from modules.focused_reports.prompt_specs import get_prompt_spec
from modules.intents.intent_contract import PERSON_DUAL
from modules.payments.report_delivery_service import SITE_URL

FOCUSED_PRICE_RUPEES = 51

BASE_TO_FOCUSED = {
    "sadhesati_report": ("current_phase_meaning", "important_years_ahead", "major_kundali_strengths"),
    "financial_report": ("income_increase_timing", "money_growth_periods"),
    "love_relationship_report": ("long_term_compatibility", "emotional_communication_fit", "strengthen_relationship"),
    "marriage_report": ("marriage_talks_current_period", "kundali_match_for_marriage", "long_term_compatibility"),
    "startup_suggestion_report": ("business_start_timing", "new_venture_partnership_timing"),
    "love_marriage_report": ("relationship_to_marriage_window", "relationship_lead_to_marriage", "kundali_match_for_marriage"),
    "government_job_report": ("exam_preparation_period", "job_search_start_timing", "next_strong_career_period"),
    "foreign_travel_report": ("going_abroad_timing", "foreign_work_timing", "foreign_settlement_timing"),
    "business_report": ("business_start_timing", "business_growth_timing", "new_venture_partnership_timing"),
    "career_report": ("promotion_timing", "job_change_now", "best_career_years"),
    "gemstone_consultation": ("major_kundali_strengths",),
    # Every focused report reads the buyer's own chart; none analyses a child, so none is suggested here.
    "children_parenting_report": (),
    "delay_in_marriage_report": ("marriage_delay_easing", "marriage_talks_current_period", "kundali_match_for_marriage"),
    "financial_stability_report": ("money_growth_periods", "income_increase_timing"),
    "jupiter_transit_report": ("important_years_ahead", "best_career_years", "money_growth_periods"),
    "lifestyle_analysis_report": (),
    "love_disappointment_report": ("current_phase_meaning",),
    "problem_in_marriage_report": ("strengthen_relationship", "emotional_communication_fit", "relationship_care_periods"),
    "mood_mental_health_report": ("current_phase_meaning", "natural_strengths"),
    "property_report": ("property_current_period", "property_strongest_period"),
    "saturn_transit_report": ("current_phase_meaning", "best_career_years", "major_kundali_strengths"),
    "second_marriage_report": ("marriage_chances_timing", "marriage_talks_current_period", "kundali_match_for_marriage"),
    "divorce_possibility_report": ("strengthen_relationship", "emotional_communication_fit"),
    # No focused report covers legal matters; generic life or obstacle topics are not suggested in their place.
    "legal_disputes_report": (),
    "spouse_nature_report": ("marriage_chances_timing", "kundali_match_for_marriage"),
}


def focused_report_url(question_key: str, language: str = "en") -> str:
    prefix = "/hi" if language_key(language) == "hi" else ""
    return f"{SITE_URL}{prefix}/reports/focused/{question_key.replace('_', '-')}"


def related_focused_reports(base_slug: str, language: str = "en") -> list:
    """[{title, price, url, two_person}] for a base report's PDF; [] when nothing is suggested or there is no mapping."""
    lang = language_key(language)
    items = []
    for key in BASE_TO_FOCUSED.get(base_slug, ()):
        spec = get_prompt_spec(key)
        items.append({"title": spec.title.get(lang), "price": FOCUSED_PRICE_RUPEES, "url": focused_report_url(key, lang),
                      "two_person": spec.person_mode == PERSON_DUAL})
    return items
