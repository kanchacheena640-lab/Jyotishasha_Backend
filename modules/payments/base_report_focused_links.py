"""Related Rs51 Focused Reports listed at the end of each Base (standard) Report PDF.

A simple static mapping, 3 focused question keys per base report. Titles come from the focused prompt specs (the
same product titles the focused pages and PDFs use) and URLs are the live focused pages, EN or /hi/ to match the PDF.
"""
from modules.focused_reports.prompt_assembler import language_key
from modules.focused_reports.prompt_specs import get_prompt_spec
from modules.payments.report_delivery_service import SITE_URL

FOCUSED_PRICE_RUPEES = 51

BASE_TO_FOCUSED = {
    "sadhesati_report": ("major_kundali_obstacles", "current_phase_meaning", "areas_needing_attention"),
    "financial_report": ("income_increase_timing", "money_growth_periods", "financial_pressure_easing"),
    "love_relationship_report": ("relationship_strengths_risks", "long_term_compatibility", "strengthen_relationship"),
    "marriage_report": ("marriage_chances_timing", "strongest_marriage_periods", "kundali_match_for_marriage"),
    "startup_suggestion_report": ("business_start_timing", "new_venture_partnership_timing", "best_business_periods"),
    "love_marriage_report": ("relationship_lead_to_marriage", "relationship_to_marriage_window", "kundali_match_for_marriage"),
    "government_job_report": ("job_search_start_timing", "next_strong_career_period", "exam_preparation_period"),
    "foreign_travel_report": ("going_abroad_timing", "foreign_settlement_timing", "foreign_work_timing"),
    "business_report": ("business_growth_timing", "best_business_periods", "business_expansion_timing"),
    "career_report": ("promotion_timing", "best_career_years", "job_change_now"),
    "gemstone_consultation": ("natural_strengths", "major_kundali_strengths", "major_kundali_obstacles"),
    "children_parenting_report": ("important_years_ahead", "current_phase_meaning", "natural_strengths"),
    "delay_in_marriage_report": ("marriage_delay_reason", "marriage_delay_easing", "marriage_chances_timing"),
    "financial_stability_report": ("financial_improvement_timing", "debt_pressure_easing", "money_growth_periods"),
    "jupiter_transit_report": ("important_years_ahead", "next_life_change_period", "best_career_years"),
    "lifestyle_analysis_report": ("natural_strengths", "focus_to_use_strengths", "life_direction"),
    "love_disappointment_report": ("relationship_care_periods", "emotional_communication_fit", "marriage_chances_timing"),
    "problem_in_marriage_report": ("conflict_areas", "strengthen_relationship", "emotional_communication_fit"),
    "mood_mental_health_report": ("current_phase_meaning", "areas_needing_attention", "natural_strengths"),
    "property_report": ("property_purchase_timing", "own_home_timing", "property_strongest_period"),
    "saturn_transit_report": ("current_phase_meaning", "major_kundali_obstacles", "next_life_change_period"),
    "second_marriage_report": ("marriage_chances_timing", "strongest_marriage_periods", "kundali_match_for_marriage"),
    "divorce_possibility_report": ("conflict_areas", "relationship_strengths_risks", "strengthen_relationship"),
    "legal_disputes_report": ("areas_needing_attention", "major_kundali_obstacles", "current_phase_meaning"),
    "spouse_nature_report": ("kundali_match_for_marriage", "long_term_compatibility", "marriage_chances_timing"),
}


def focused_report_url(question_key: str, language: str = "en") -> str:
    prefix = "/hi" if language_key(language) == "hi" else ""
    return f"{SITE_URL}{prefix}/reports/focused/{question_key.replace('_', '-')}"


def related_focused_reports(base_slug: str, language: str = "en") -> list:
    """[{title, price, url}] for a base report's PDF; [] for any product without a mapping."""
    lang = language_key(language)
    return [{"title": get_prompt_spec(key).title.get(lang), "price": FOCUSED_PRICE_RUPEES,
             "url": focused_report_url(key, lang)} for key in BASE_TO_FOCUSED.get(base_slug, ())]
