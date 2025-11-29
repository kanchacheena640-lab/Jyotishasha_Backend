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


# ⭐ SCORE ENGINE (reads English values always)
def _score_and_reasons(p, rules, language="en"):
    score, reasons = 0, []

    # UI text
    if language == "hi":
        word_allowed = "शुभ"
        word_avoid = "अशुभ"
        word_neutral = "सामान्य"

        prefix_tithi = "तिथि"
        prefix_weekday = "वार"
        prefix_nakshatra = "नक्षत्र"
        prefix_yoga = "योग"
        prefix_karan = "करण"

        # Display values from Hindi version
        t_display = p["tithi"]["name_hi"]
        w_display = p["weekday_hi"]
        nk_display = p["nakshatra"]["name_hi"]
        yoga_display = p["yoga"]["name_hi"]
        karan_display = p["karan"]["name_hi"]

    else:
        word_allowed = "allowed"
        word_avoid = "avoided"
        word_neutral = "neutral"

        prefix_tithi = "Tithi"
        prefix_weekday = "Weekday"
        prefix_nakshatra = "Nakshatra"
        prefix_yoga = "Yoga"
        prefix_karan = "Karan"

        # Display values from English
        t_display = p["tithi"]["name_en"]
        w_display = p["weekday_en"]
        nk_display = p["nakshatra"]["name_en"]
        yoga_display = p["yoga"]["name_en"]
        karan_display = p["karan"]["name_en"]

    # RAW English values for scoring
    t_num = p["tithi"]["number"]
    w = p["weekday_en"]
    nk = p["nakshatra"]["name_en"]
    yoga = p["yoga"]["name_en"]
    karan = p["karan"]["name_en"]

    # ---------------- TITHI ----------------
    if t_num in rules.get("allowed_tithis", []):
        score += 2
        reasons.append(f"{prefix_tithi} {t_display} {word_allowed}")
    elif t_num in rules.get("avoid_tithis", []):
        score -= 3
        reasons.append(f"{prefix_tithi} {t_display} {word_avoid}")
    else:
        reasons.append(f"{prefix_tithi} {t_display} {word_neutral}")

    # ---------------- WEEKDAY ----------------
    if w in rules.get("allowed_weekdays", []):
        score += 2
        reasons.append(f"{prefix_weekday} {w_display} {word_allowed}")
    elif w in rules.get("avoid_weekdays", []):
        score -= 2
        reasons.append(f"{prefix_weekday} {w_display} {word_avoid}")
    else:
        reasons.append(f"{prefix_weekday} {w_display} {word_neutral}")

    # ---------------- NAKSHATRA ----------------
    if nk in rules.get("avoid_nakshatras", []):
        score -= 5
        reasons.append(f"{prefix_nakshatra} {nk_display} {word_avoid}")
    elif nk in rules.get("allowed_nakshatras", []):
        score += 3
        reasons.append(f"{prefix_nakshatra} {nk_display} {word_allowed}")
    else:
        reasons.append(f"{prefix_nakshatra} {nk_display} {word_neutral}")

    # ---------------- YOGA ----------------
    if yoga in rules.get("avoid_yogas", []):
        score -= 2
        reasons.append(f"{prefix_yoga} {yoga_display} {word_avoid}")

    # ---------------- KARAN ----------------
    if karan in rules.get("avoid_karans", []):
        score -= 3
        reasons.append(f"{prefix_karan} {karan_display} {word_avoid}")

    return score, reasons


# ⭐ MAIN
def next_best_dates(activity, lat, lon, days=30, top_k=10, language="en"):

    language = (language or "en").lower()
    if language != "hi":
        language = "en"

    rules, file_path = _load_rules(activity)
    today = datetime.now().date()

    out = []

    for i in range(days):
        d = today + timedelta(days=i)

        # Panchang → must return EN + HI both
        p = calculate_panchang(d, lat, lon, language)

        score, reasons = _score_and_reasons(p, rules, language)

        out.append({
            "date": p["date"],
            "weekday": p["weekday_hi"] if language == "hi" else p["weekday_en"],
            "nakshatra": p["nakshatra"]["name_hi"] if language == "hi" else p["nakshatra"]["name_en"],
            "tithi": p["tithi"]["name_hi"] if language == "hi" else p["tithi"]["name_en"],
            "score": score,
            "reasons": reasons,
            "language": language,
            "rules_file": file_path
        })

    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:top_k]
