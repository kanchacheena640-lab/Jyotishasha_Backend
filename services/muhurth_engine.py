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


# ⭐ UPDATED: multilingual reasons
def _score_and_reasons(p, rules, language="en"):
    score, reasons = 0, []

    # ---------------- HINDI WORD SET ----------------
    if language == "hi":
        word_allowed = "शुभ"
        word_avoid = "अशुभ"
        word_neutral = "सामान्य"

        prefix_tithi = "तिथि"
        prefix_weekday = "वार"
        prefix_nakshatra = "नक्षत्र"

    else:
        # Default English
        word_allowed = "allowed"
        word_avoid = "avoided"
        word_neutral = "neutral"

        prefix_tithi = "Tithi"
        prefix_weekday = "Weekday"
        prefix_nakshatra = "Nakshatra"

    # ---------------- TITHI ----------------
    tithi_name = p["tithi"]["name"]
    tnum = p["tithi"]["number"]

    if tnum in rules.get("allowed_tithis", []):
        score += 2
        reasons.append(f"{prefix_tithi} {tithi_name} {word_allowed}")
    elif tnum in rules.get("avoid_tithis", []):
        score -= 3
        reasons.append(f"{prefix_tithi} {tithi_name} {word_avoid}")
    else:
        reasons.append(f"{prefix_tithi} {tithi_name} {word_neutral}")

    # ---------------- WEEKDAY ----------------
    weekday = p["weekday"]

    if weekday in rules.get("allowed_weekdays", []):
        score += 2
        reasons.append(f"{prefix_weekday} {weekday} {word_allowed}")
    elif weekday in rules.get("avoid_weekdays", []):
        score -= 2
        reasons.append(f"{prefix_weekday} {weekday} {word_avoid}")
    else:
        reasons.append(f"{prefix_weekday} {weekday} {word_neutral}")

    # ---------------- NAKSHATRA ----------------
    nk = p["nakshatra"]["name"]

    if nk in rules.get("avoid_nakshatras", []):
        score -= 5
        reasons.append(f"{prefix_nakshatra} {nk} {word_avoid}")
    elif "allowed_nakshatras" in rules and nk in rules["allowed_nakshatras"]:
        score += 3
        reasons.append(f"{prefix_nakshatra} {nk} {word_allowed}")
    else:
        reasons.append(f"{prefix_nakshatra} {nk} {word_neutral}")

    # ---------------- YOGA ----------------
    yoga = p["yoga"]["name"]
    if yoga in rules.get("avoid_yogas", []):
        score -= 2
        # Yoga not translated — stays same
        if language == "hi":
            reasons.append(f"योग {yoga} {word_avoid}")
        else:
            reasons.append(f"Yoga {yoga} {word_avoid}")

    # ---------------- KARAN ----------------
    karan = p["karan"]["name"]
    if karan in rules.get("avoid_karans", []):
        score -= 3
        if language == "hi":
            reasons.append(f"करण {karan} {word_avoid}")
        else:
            reasons.append(f"Karan {karan} {word_avoid}")

    return score, reasons



# ⭐ main function with language support
def next_best_dates(activity, lat, lon, days=30, top_k=10, language="en"):

    # Safe language
    language = (language or "en").lower()
    if language != "hi":
        language = "en"

    rules, file_path = _load_rules(activity)
    today = datetime.now().date()
    out = []

    for i in range(days):
        d = today + timedelta(days=i)

        # Panchang is already bilingual
        p = calculate_panchang(d, lat, lon, language)

        score, reasons = _score_and_reasons(p, rules, language)

        out.append({
            "date": p["date"],
            "weekday": p["weekday"],
            "nakshatra": p["nakshatra"]["name"],
            "tithi": p["tithi"]["name"],
            "score": score,
            "reasons": reasons,
            "language": language,
            "rules_file": file_path
        })

    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:top_k]
