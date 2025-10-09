# muhurth_engine.py
import json, os
from datetime import datetime, timedelta
from services.panchang_engine import calculate_panchang

RULES_DIR = os.path.join(os.path.dirname(__file__), "..", "rules")

def _load_rules(activity):
    file_path = os.path.join(RULES_DIR, f"{activity}.json")
    with open(file_path, encoding="utf-8") as f:
        return json.load(f), file_path

def _score_and_reasons(p, rules):
    score, reasons = 0, []

    # Tithi
    if p["tithi"]["number"] in rules.get("allowed_tithis", []):
        score += 2; reasons.append(f"Tithi {p['tithi']['name']} allowed")
    elif p["tithi"]["number"] in rules.get("avoid_tithis", []):
        score -= 3; reasons.append(f"Tithi {p['tithi']['name']} avoided")
    else:
        reasons.append(f"Tithi {p['tithi']['name']} neutral")

    # Weekday
    if p["weekday"] in rules.get("allowed_weekdays", []):
        score += 2; reasons.append(f"Weekday {p['weekday']} allowed")
    elif p["weekday"] in rules.get("avoid_weekdays", []):
        score -= 2; reasons.append(f"Weekday {p['weekday']} avoided")
    else:
        reasons.append(f"Weekday {p['weekday']} neutral")

    # Nakshatra
    nk = p["nakshatra"]["name"]
    if nk in rules.get("avoid_nakshatras", []):
        score -= 5; reasons.append(f"Nakshatra {nk} avoided")
    elif "allowed_nakshatras" in rules and nk in rules["allowed_nakshatras"]:
        score += 3; reasons.append(f"Nakshatra {nk} favorable")
    else:
        reasons.append(f"Nakshatra {nk} neutral")

    # Yoga
    if p["yoga"]["name"] in rules.get("avoid_yogas", []):
        score -= 2; reasons.append(f"Yoga {p['yoga']['name']} avoided")

    # Karan
    if p["karan"]["name"] in rules.get("avoid_karans", []):
        score -= 3; reasons.append(f"Karan {p['karan']['name']} avoided")

    return score, reasons

def next_best_dates(activity, lat, lon, days=30, top_k=10):
    """
    Return best dates in coming 'days' for given activity.
    Each result includes file path of rules used.
    """
    rules, file_path = _load_rules(activity)
    today = datetime.now().date()
    out = []

    for i in range(days):
        d = today + timedelta(days=i)
        p = calculate_panchang(d, lat, lon)
        score, reasons = _score_and_reasons(p, rules)
        out.append({
            "date": p["date"],
            "weekday": p["weekday"],
            "score": score,
            "reasons": reasons,
            "rules_file": file_path   # ✅ file path added
        })

    # sort by score
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:top_k]
