# muhurth_engine.py
import json, os
from datetime import datetime, timedelta
from services.panchang_engine import calculate_panchang

RULES_DIR = os.path.join(os.path.dirname(__file__), "..", "rules")


def _load_rules(activity):
    safe_name = activity.replace("-", "_").replace(" ", "_")
    file_path = os.path.join(RULES_DIR, f"{safe_name}.json")
    with open(file_path, encoding="utf-8") as f:
        return json.load(f), file_path


# ⭐ MULTILINGUAL + SAFE SCORING (English names only)
def _score_and_reasons(p, rules, language="en"):
    score, reasons = 0, []

    # ---------------- LANGUAGE PACK ----------------
    if language == "hi":
        word_allowed = "शुभ"
        word_avoid = "अशुभ"
        word_neutral = "सामान्य"

        prefix_tithi = "तिथि"
        prefix_weekday = "वार"
        prefix_nakshatra = "नक्षत्र"
        prefix_yoga = "योग"
        prefix_karan = "करण"
    else:
        word_allowed = "allowed"
        word_avoid = "avoided"
        word_neutral = "neutral"

        prefix_tithi = "Tithi"
        prefix_weekday = "Weekday"
        prefix_nakshatra = "Nakshatra"
        prefix_yoga = "Yoga"
        prefix_karan = "Karan"

    # ⭐ ALWAYS USE ENGLISH FOR SCORING
    t_name = p["tithi"].get("name_en") or p["tithi"]["name"]
    t_num = p["tithi"]["number"]

    w = p.get("weekday_en") or p["weekday"]

    nk = p["nakshatra"].get("name_en") or p["nakshatra"]["name"]

    yoga = p["yoga"].get("name_en") or p["yoga"]["name"]
    karan = p["karan"].get("name_en") or p["karan"]["name"]

    # ---------------- TITHI ----------------
    if t_num in rules.get("allowed_tithis", []):
        score += 2
        reasons.append(f"{prefix_tithi} {t_name} {word_allowed}")
    elif t_num in rules.get("avoid_tithis", []):
        score -= 3
        reasons.append(f"{prefix_tithi} {t_name} {word_avoid}")
    else:
        reasons.append(f"{prefix_tithi} {t_name} {word_neutral}")

    # ---------------- WEEKDAY ----------------
    if w in rules.get("allowed_weekdays", []):
        score += 2
        reasons.append(f"{prefix_weekday} {w} {word_allowed}")
    elif w in rules.get("avoid_weekdays", []):
        score -= 2
        reasons.append(f"{prefix_weekday} {w} {word_avoid}")
    else:
        reasons.append(f"{prefix_weekday} {w} {word_neutral}")

    # ---------------- NAKSHATRA ----------------
    if nk in rules.get("avoid_nakshatras", []):
        score -= 5
        reasons.append(f"{prefix_nakshatra} {nk} {word_avoid}")
    elif nk in rules.get("allowed_nakshatras", []):
        score += 3
        reasons.append(f"{prefix_nakshatra} {nk} {word_allowed}")
    else:
        reasons.append(f"{prefix_nakshatra} {nk} {word_neutral}")

    # ---------------- YOGA ----------------
    if yoga in rules.get("avoid_yogas", []):
        score -= 2
        reasons.append(f"{prefix_yoga} {yoga} {word_avoid}")

    # ---------------- KARAN ----------------
    if karan in rules.get("avoid_karans", []):
        score -= 3
        reasons.append(f"{prefix_karan} {karan} {word_avoid}")

    return score, reasons


# ⭐ MAIN FUNCTION (Display Hindi/English — Scoring always EN)
def next_best_dates(activity, lat, lon, days=30, top_k=10, language="en"):

    # Normalize input
    language = (language or "en").lower()
    if language not in ["hi", "en"]:
        language = "en"

    rules, file_path = _load_rules(activity)
    today = datetime.now().date()

    out = []

    for i in range(days):
        d = today + timedelta(days=i)

        # Panchang engine bilingual output
        p = calculate_panchang(d, lat, lon, language)

        # Score using EN names only
        score, reasons = _score_and_reasons(p, rules, language)

        # Display based on selected language
        nakshatra_display = (
            p["nakshatra"].get("name_hi") if language == "hi"
            else p["nakshatra"].get("name_en")
        )

        tithi_display = (
            p["tithi"].get("name_hi") if language == "hi"
            else p["tithi"].get("name_en")
        )

        weekday_display = (
            p.get("weekday_hi") if language == "hi"
            else p.get("weekday_en")
        )

        out.append({
            "date": p["date"],
            "weekday": weekday_display,
            "nakshatra": nakshatra_display,
            "tithi": tithi_display,
            "score": score,
            "reasons": reasons,
            "language": language,
            "rules_file": file_path,
        })

    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:top_k]
