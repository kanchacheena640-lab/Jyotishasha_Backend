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


# ⭐ MULTILINGUAL REASONS (CLEAN + CRASH PROOF)
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

    # ---------------- TITHI ----------------
    t_name = p["tithi"]["name"]
    t_num = p["tithi"]["number"]

    if t_num in rules.get("allowed_tithis", []):
        score += 2
        reasons.append(f"{prefix_tithi} {t_name} {word_allowed}")
    elif t_num in rules.get("avoid_tithis", []):
        score -= 3
        reasons.append(f"{prefix_tithi} {t_name} {word_avoid}")
    else:
        reasons.append(f"{prefix_tithi} {t_name} {word_neutral}")

    # ---------------- WEEKDAY ----------------
    w = p["weekday"]

    if w in rules.get("allowed_weekdays", []):
        score += 2
        reasons.append(f"{prefix_weekday} {w} {word_allowed}")
    elif w in rules.get("avoid_weekdays", []):
        score -= 2
        reasons.append(f"{prefix_weekday} {w} {word_avoid}")
    else:
        reasons.append(f"{prefix_weekday} {w} {word_neutral}")

    # ---------------- NAKSHATRA ----------------
    nk = p["nakshatra"]["name"]

    if nk in rules.get("avoid_nakshatras", []):
        score -= 5
        reasons.append(f"{prefix_nakshatra} {nk} {word_avoid}")
    elif nk in rules.get("allowed_nakshatras", []):
        score += 3
        reasons.append(f"{prefix_nakshatra} {nk} {word_allowed}")
    else:
        reasons.append(f"{prefix_nakshatra} {nk} {word_neutral}")

    # ---------------- YOGA ----------------
    yoga = p["yoga"]["name"]
    if yoga in rules.get("avoid_yogas", []):
        score -= 2
        reasons.append(f"{prefix_yoga} {yoga} {word_avoid}")

    # ---------------- KARAN ----------------
    karan = p["karan"]["name"]
    if karan in rules.get("avoid_karans", []):
        score -= 3
        reasons.append(f"{prefix_karan} {karan} {word_avoid}")

    return score, reasons


# ⭐ MAIN FUNCTION (SAFE LANGUAGE + CLEAN OUTPUT)
def next_best_dates(activity, lat, lon, days=30, top_k=10, language="en"):

    # Clean language input
    language = (language or "en").lower()
    if language != "hi":
        language = "en"

    rules, file_path = _load_rules(activity)
    today = datetime.now().date()

    out = []

    for i in range(days):
        d = today + timedelta(days=i)

        # Panchang engine bilingual
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
