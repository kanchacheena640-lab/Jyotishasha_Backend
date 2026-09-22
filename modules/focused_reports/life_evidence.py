"""Minimum SELF Life evidence, using existing astrology primitives only."""
from dataclasses import dataclass

from modules.focused_reports.career_evidence import multi_year_dasha_summary
from modules.focused_reports.life_keys import LIFE_HORIZONS, LIFE_HOUSES, LIFE_NATAL_PLANETS
from modules.focused_reports.prompt_specs import get_prompt_spec
from modules.focused_reports.prompt_assembler import MissingEvidenceError, PromptAssemblyError, language_key, _present
from modules.focused_reports.promotion_transit_evidence import build_promotion_transit_evidence, render_promotion_transit_summary
from modules.payments.report_date_format import normalize_customer_dates, format_customer_date_range
from summary_blocks import build_summary_blocks_with_transit, build_house_lord_facts, _build_house_lord_summary, SIGN_ORDER, _flatten_dasha_sequence
from transit_engine import get_current_positions

SUMMARY_KEYS = ("birth_chart_summary", "house_lord_summary", "dasha_window_summary")
TRANSIT_PLANETS = ("Jupiter", "Saturn")
SUPPORTED_KEYS = frozenset((*SUMMARY_KEYS, "dasha_sequence", *TRANSIT_PLANETS))


@dataclass(frozen=True)
class LifeEvidence:
    language: str
    sections: dict
    transit_evidence: dict
    report_date: str | None
    horizon_end: str | None
    report_period: str | None


def collect_life_evidence(question_key, kundali, language="en"):
    spec = get_prompt_spec(question_key)
    if question_key not in LIFE_HORIZONS:
        raise ValueError("Question has no Life evidence collector.")
    if spec.person_mode != "single" or spec.intent_slug not in ("life_turning_points", "life_direction_and_strengths"):
        raise PromptAssemblyError("Life evidence requires the customer's own single chart.")
    lang = language_key(language)
    required = {r.key for r in spec.evidence_requirements}
    if required - SUPPORTED_KEYS:
        raise MissingEvidenceError(sorted(required - SUPPORTED_KEYS))
    if not isinstance(kundali, dict) or kundali.get("lagna_sign") not in SIGN_ORDER or not kundali.get("planets"):
        raise MissingEvidenceError(("birth_chart_summary", "house_lord_summary"))
    months = LIFE_HORIZONS[question_key]
    transits = {}
    active_lords = set()
    if months:
        transits = build_promotion_transit_evidence(kundali["lagna_sign"],
            horizon_months=months, selected_planets=TRANSIT_PLANETS)
        sequence = multi_year_dasha_summary(kundali, transits["as_of"], transits["horizon_end"])
        active_lords = {r[k] for r in _flatten_dasha_sequence(kundali.get("Mahadasha"))
                        if r["start"] <= transits["horizon_end"] and r["end"] >= transits["as_of"]
                        for k in ("mahadasha", "planet")}
    houses = set(LIFE_HOUSES[question_key])
    all_facts = build_house_lord_facts(kundali)
    houses.update(f["house"] for f in all_facts if f["lord"] in active_lords)
    facts = [f for f in all_facts if f["house"] in houses]
    if len(facts) != len(houses) or any(f.get("lord_sign") not in SIGN_ORDER or f.get("lord_house") not in range(1, 13) for f in facts):
        raise MissingEvidenceError(("house_lord_summary",))
    planets = kundali.get("planets")
    if not isinstance(planets, list) or any(not isinstance(p, dict) for p in planets):
        raise MissingEvidenceError(("birth_chart_summary",))
    needed_planets = set(LIFE_NATAL_PLANETS) | active_lords
    selected = [p for p in planets if p.get("name") in needed_planets]
    if len(selected) != len(needed_planets) or {p.get("name") for p in selected} != needed_planets or any(
        p.get("sign") not in SIGN_ORDER or p.get("house") not in range(1, 13) for p in selected):
        raise MissingEvidenceError(("birth_chart_summary",))
    # Only the natal summary uses selected planets; house/lord facts above use
    # the complete authoritative chart. No transit calculation for natal reports.
    blocks = build_summary_blocks_with_transit({**kundali, "planets": selected},
                                               get_current_positions() if months else {})
    available = {key: blocks.get(key, "") for key in SUMMARY_KEYS if key in required}
    available["house_lord_summary"] = _build_house_lord_summary(facts)
    missing = [key for key, value in available.items() if not _present(value)]
    if missing:
        raise MissingEvidenceError(missing)
    if months:
        if "dasha_sequence" in required:
            available["dasha_sequence"] = sequence
        elif "dasha_window_summary" in required:
            available["dasha_window_summary"] += "\nMD/AD windows covering the report period:\n" + sequence
        for name in TRANSIT_PLANETS:
            selected = [p for p in transits["planets"] if p["planet"] == name]
            if len(selected) != 1 or not selected[0].get("sign_residence") or not selected[0].get("motion_periods"):
                raise MissingEvidenceError((name,))
            available[name] = render_promotion_transit_summary({**transits, "planets": selected}, lang)
    sections = {r.key: normalize_customer_dates(available[r.key], lang) for r in spec.evidence_requirements}
    return LifeEvidence(lang, sections, transits, transits.get("as_of"), transits.get("horizon_end"),
        format_customer_date_range(transits["as_of"], transits["horizon_end"], lang) if months else None)
