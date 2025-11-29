# muhurth_engine.py
import json, os
from datetime import datetime, timedelta
from services.panchang_engine import calculate_panchang

RULES_DIR = os.path.join(os.path.dirname(__file__), "..", "rules")

# -------------------- FIXED EN→HI MAPPINGS --------------------
TITHI_HI = {
    "Pratipada": "प्रतिपदा", "Dvitiya": "द्वितीया", "Tritiya": "तृतीया",
    "Chaturthi": "चतुर्थी", "Panchami": "पंचमी", "Shashthi": "षष्ठी",
    "Saptami": "सप्तमी", "Ashtami": "अष्टमी", "Navami": "नवमी",
    "Dashami": "दशमी", "Ekadashi": "एकादशी", "Dwadashi": "द्वादशी",
    "Trayodashi": "त्रयोदशी", "Chaturdashi": "चतुर्दशी",
    "Purnima": "पूर्णिमा", "Amavasya": "अमावस्या"
}

WEEKDAY_HI = {
    "Monday": "सोमवार", "Tuesday": "मंगलवार", "Wednesday": "बुधवार",
    "Thursday": "गुरुवार", "Friday": "शुक्रवार", "Saturday": "शनिवार",
    "Sunday": "रविवार"
}

NAKSHATRA_HI = {
    "Ashwini": "अश्विनी", "Bharani": "भरणी", "Krittika": "कृत्तिका",
    "Rohini": "रोहिणी", "Mrigashira": "मृगशिरा", "Ardra": "आर्द्रा",
    "Punarvasu": "पुनर्वसु", "Pushya": "पुष्य", "Ashlesha": "अश्लेषा",
    "Magha": "मघा", "Purva Phalguni": "पूर्वा फाल्गुनी",
    "Uttara Phalguni": "उत्तर फाल्गुनी", "Hasta": "हस्त",
    "Chitra": "चित्रा", "Swati": "स्वाती", "Vishakha": "विशाखा",
    "Anuradha": "अनुराधा", "Jyeshtha": "ज्येष्ठा", "Mula": "मूला",
    "Purva Ashadha": "पूर्वाषाढ़ा", "Uttara Ashadha": "उत्तराषाढ़ा",
    "Shravana": "श्रवण", "Dhanishta": "धनिष्ठा",
    "Shatabhisha": "शतभिषा", "Purva Bhadrapada": "पूर्व भाद्रपद",
    "Uttara Bhadrapada": "उत्तर भाद्रपद", "Revati": "रेवती"
}

# -------------------- REASON TRANSLATION (FULL Hindi) --------------------
def translate_reason_full(text, tithi_en, weekday_en, nakshatra_en):
    # Step-1: Replace structural words
    text = (
        text.replace("Tithi", "तिथि")
            .replace("Weekday", "वार")
            .replace("Nakshatra", "नक्षत्र")
            .replace("Yoga", "योग")
            .replace("Karan", "करण")
            .replace("allowed", "शुभ")
            .replace("avoided", "अशुभ")
            .replace("neutral", "सामान्य")
    )

    # Step-2: Replace middle English words → Hindi dictionary
    text = text.replace(tithi_en, TITHI_HI.get(tithi_en, tithi_en))
    text = text.replace(weekday_en, WEEKDAY_HI.get(weekday_en, weekday_en))
    text = text.replace(nakshatra_en, NAKSHATRA_HI.get(nakshatra_en, nakshatra_en))

    return text


# -------------------- FULL ITEM TRANSLATION --------------------
def translate_item_to_hindi(item):
    t_en = item["tithi"]
    w_en = item["weekday"]
    n_en = item["nakshatra"]

    return {
        **item,
        "tithi": TITHI_HI.get(t_en, t_en),
        "weekday": WEEKDAY_HI.get(w_en, w_en),
        "nakshatra": NAKSHATRA_HI.get(n_en, n_en),

        # Translate each reason fully (prefix + dynamic keywords)
        "reasons": [
            translate_reason_full(r, t_en, w_en, n_en)
            for r in item["reasons"]
        ],
    }

# -------------------- LOAD RULES --------------------
def _load_rules(activity):
    safe_name = activity.replace("-", "_").replace(" ", "_")
    file_path = os.path.join(RULES_DIR, f"{safe_name}.json")
    with open(file_path, encoding="utf-8") as f:
        return json.load(f), file_path

# -------------------- SCORING ENGINE (ENGLISH ONLY) --------------------
def _score_and_reasons(p, rules):
    score, reasons = 0, []

    t_name = p["tithi"]["name"]
    t_num = p["tithi"]["number"]
    w = p["weekday"]
    nk = p["nakshatra"]["name"]
    yoga = p["yoga"]["name"]
    karan = p["karan"]["name"]

    # ---- TITHI ----
    if t_num in rules.get("allowed_tithis", []):
        score += 2
        reasons.append(f"Tithi {t_name} allowed")
    elif t_num in rules.get("avoid_tithis", []):
        score -= 3
        reasons.append(f"Tithi {t_name} avoided")
    else:
        reasons.append(f"Tithi {t_name} neutral")

    # ---- WEEKDAY ----
    if w in rules.get("allowed_weekdays", []):
        score += 2
        reasons.append(f"Weekday {w} allowed")
    elif w in rules.get("avoid_weekdays", []):
        score -= 2
        reasons.append(f"Weekday {w} avoided")
    else:
        reasons.append(f"Weekday {w} neutral")

    # ---- NAKSHATRA ----
    if nk in rules.get("avoid_nakshatras", []):
        score -= 5
        reasons.append(f"Nakshatra {nk} avoided")
    elif nk in rules.get("allowed_nakshatras", []):
        score += 3
        reasons.append(f"Nakshatra {nk} allowed")
    else:
        reasons.append(f"Nakshatra {nk} neutral")

    # ---- YOGA ----
    if yoga in rules.get("avoid_yogas", []):
        score -= 2
        reasons.append(f"Yoga {yoga} avoided")

    # ---- KARAN ----
    if karan in rules.get("avoid_karans", []):
        score -= 3
        reasons.append(f"Karan {karan} avoided")

    return score, reasons

# -------------------- MAIN ENGINE --------------------
def next_best_dates(activity, lat, lon, days=30, top_k=10, language="en"):
    # Force English scoring
    is_hindi = (language or "en").lower() == "hi"
    language = "en"

    rules, file_path = _load_rules(activity)
    today = datetime.now().date()

    out = []

    for i in range(days):
        d = today + timedelta(days=i)

        # Panchang always in ENGLISH
        p = calculate_panchang(d, lat, lon, "en")

        score, reasons = _score_and_reasons(p, rules)

        item = {
            "date": p["date"],
            "weekday": p["weekday"],
            "nakshatra": p["nakshatra"]["name"],
            "tithi": p["tithi"]["name"],
            "score": score,
            "reasons": reasons,
            "language": "en",
            "rules_file": file_path
        }

        # Hindi output requested → translate final item
        if is_hindi:
            item = translate_item_to_hindi(item)
            item["language"] = "hi"

        out.append(item)

    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:top_k]
