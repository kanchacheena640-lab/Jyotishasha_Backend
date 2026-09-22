"""Focused-only adapter over existing dual-chart astrology primitives.

Input: {user: {name, dob, tob, pob, lat, lng}, partner: same,
boy_is_user: bool}. latitude/longitude aliases are also accepted. Matching
role order is explicit because the existing Varna calculation is asymmetric.
No DOB-only fallback, caller-supplied compatibility scores, or delivery code.
"""
from dataclasses import dataclass
from datetime import date, time
import json

from full_kundali_api import calculate_full_kundali
from modules.love.love_data_collector import _coordinate
from modules.love.service_love import _extract_moon
from modules.love.ashtakoot_love import compute_ashtakoot
from summary_blocks import build_house_lord_facts, SIGN_ORDER
from modules.focused_reports.career_evidence import multi_year_dasha_summary
from modules.focused_reports.relationship_keys import RELATIONSHIP_HORIZONS, RELATIONSHIP_SELECTIONS, ALL_KOOTAS
from modules.focused_reports.prompt_specs import get_prompt_spec
from modules.focused_reports.prompt_assembler import MissingEvidenceError, PromptAssemblyError, language_key
from modules.focused_reports.promotion_transit_evidence import build_promotion_transit_evidence, render_promotion_transit_summary
from modules.payments.report_date_format import normalize_customer_dates, format_customer_date_range


@dataclass(frozen=True)
class RelationshipEvidence:
    language: str
    sections: dict
    horizon_months: int | None
    report_period: str | None


def _profile(value, label):
    if not isinstance(value, dict):
        raise MissingEvidenceError((label + " birth profile",))
    for key in ("name", "dob", "tob", "pob"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise MissingEvidenceError((label + " " + key,))
    try:
        date.fromisoformat(value["dob"])
        time.fromisoformat(value["tob"])
    except ValueError:
        raise MissingEvidenceError((label + " birth date/time",)) from None
    lat = _coordinate(value.get("latitude", value.get("lat")), 90)
    lng = _coordinate(value.get("longitude", value.get("lng")), 180)
    if lat is None or lng is None or (lat == 0 and lng == 0):
        raise MissingEvidenceError((label + " coordinates",))
    return {**{k: value[k] for k in ("name", "dob", "tob", "pob")}, "lat": lat, "lng": lng}


def _natal(chart, houses, label):
    if not isinstance(chart, dict) or chart.get("lagna_sign") not in SIGN_ORDER:
        raise MissingEvidenceError((label + " natal",))
    planets = chart.get("planets")
    if not isinstance(planets, list) or any(not isinstance(p, dict) for p in planets):
        raise MissingEvidenceError((label + " planets",))
    facts = [f for f in build_house_lord_facts(chart) if f["house"] in houses]
    if len(facts) != len(houses) or any(not f["lord_house"] or f["lord_sign"] not in SIGN_ORDER for f in facts):
        raise MissingEvidenceError((label + " house/lord facts",))
    selected = [p for p in planets if p.get("name") in ("Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn")]
    if len({p["name"] for p in selected}) != 6 or any(p.get("sign") not in SIGN_ORDER or p.get("house") not in range(1, 13) for p in selected):
        raise MissingEvidenceError((label + " natal placements",))
    return label + ": " + json.dumps({"lagna": chart["lagna_sign"], "houses": facts,
        "planets": [{k: p.get(k) for k in ("name", "sign", "house")} for p in selected]}, ensure_ascii=False)


def collect_relationship_evidence(question_key, payload, language="en"):
    spec = get_prompt_spec(question_key)
    if question_key not in RELATIONSHIP_HORIZONS or spec.person_mode != "dual":
        raise PromptAssemblyError("Relationship collector requires an explicit dual-person question.")
    lang = language_key(language)
    months = RELATIONSHIP_HORIZONS[question_key]
    supported = {"user_natal", "partner_natal", "compatibility_facts"}
    if months:
        supported |= {"both_dasha_windows", "both_relevant_transits"}
    if {r.key for r in spec.evidence_requirements} != supported:
        raise MissingEvidenceError(("unsupported Relationship evidence requirements",))
    if not isinstance(payload, dict):
        raise MissingEvidenceError(("both birth profiles",))
    profiles = [_profile(payload.get(key), key) for key in ("user", "partner")]
    if type(payload.get("boy_is_user")) is not bool:
        raise MissingEvidenceError(("explicit Ashtakoot role order (boy_is_user)",))
    charts = [calculate_full_kundali(name=p["name"], dob=p["dob"], tob=p["tob"],
              lat=p["lat"], lon=p["lng"], language=lang) for p in profiles]
    houses, components = RELATIONSHIP_SELECTIONS[question_key]
    sections = {key: _natal(chart, houses, label) for key, chart, label in zip(
        ("user_natal", "partner_natal"), charts, ("Primary person", "Partner"))}
    moons = [_extract_moon(chart) for chart in charts]
    if any(not m.get("nakshatra") or _coordinate(m.get("degree"), 30) is None or not 0 <= float(m["degree"]) < 30 for m in moons):
        raise MissingEvidenceError(("both Moon facts",))
    groom, bride = moons if payload["boy_is_user"] else moons[::-1]
    match = compute_ashtakoot(bride_moon=bride, groom_moon=groom)
    kootas = match.get("kootas", {})
    if any(not isinstance(kootas.get(k), dict) or kootas[k].get("status") in (None, "invalid")
           or kootas[k].get("score") is None for k in components):
        raise MissingEvidenceError(("authoritative compatibility components",))
    facts = {k: kootas[k] for k in components}
    if components == ALL_KOOTAS:
        facts.update(total_score=match["total_score"], max_score=match["max_score"])
    sections["compatibility_facts"] = ("Existing Ashtakoot facts; not a probability. Groom role: " +
        ("Primary person" if payload["boy_is_user"] else "Partner") + ". " + json.dumps(facts, ensure_ascii=False))
    period = None
    if months:
        transits = [build_promotion_transit_evidence(c["lagna_sign"], horizon_months=months,
                    selected_planets=("Jupiter", "Saturn")) for c in charts]
        if (transits[0]["as_of"], transits[0]["horizon_end"]) != (transits[1]["as_of"], transits[1]["horizon_end"]):
            raise MissingEvidenceError(("aligned dual timing horizons",))
        dasha, transit = [], []
        for label, chart, t in zip(("Primary person", "Partner"), charts, transits):
            if {p["planet"] for p in t["planets"]} != {"Jupiter", "Saturn"} or any(
                not p.get("sign_residence") or not p.get("motion_periods") for p in t["planets"]):
                raise MissingEvidenceError((label + " transits",))
            dasha.append(label + ":\n" + multi_year_dasha_summary(chart, t["as_of"], t["horizon_end"]))
            transit.append(label + ":\n" + render_promotion_transit_summary(t, lang))
        sections.update(both_dasha_windows="\n".join(dasha), both_relevant_transits="\n".join(transit))
        period = format_customer_date_range(transits[0]["as_of"], transits[0]["horizon_end"], lang)
    return RelationshipEvidence(lang, {k: normalize_customer_dates(v, lang) for k, v in sections.items()}, months, period)
