from services.card_config import CARD_DESIGN_MAP
import json
import os
import random


BASE_DIR = os.path.dirname(__file__)

with open(os.path.join(BASE_DIR, "remedy_data.json"), "r", encoding="utf-8") as f:
    REMEDY_DATA = json.load(f)["remedies"]

def generate_cards(panchang_data, events):
    cards = []

    cards.append(build_good_morning_card(panchang_data["selected_date"]))
    cards.append(build_chaughadiya_card(panchang_data["selected_date"]))
    cards.append(build_panchak_card(panchang_data["selected_date"]))

    # Tomorrow card
    cards.append(build_tomorrow_card(panchang_data["next_date"]))

    # Festival
    festival_card = build_festival_card(events)
    if festival_card:
        cards.append(festival_card)

    # Planet
    planet_card = build_planet_card(events)
    if planet_card:
        cards.append(planet_card)

    # Remedy (only once)
    lang = panchang_data["selected_date"].get("language", "en")
    remedy_card = build_deep_remedy_card(panchang_data["selected_date"], lang=lang)
    if remedy_card:
        cards.append(remedy_card)

    # 🔥 EVENTS (wish + info)
    lang = panchang_data["selected_date"].get("language", "en")

    for e in events:
        if e.get("type") in ["festival", "vrat", "purnima", "amavasya", "pradosh", "sankashti", "vinayaka_chaturthi", "maha_shivratri", "masik_shivratri"]:
            cards.append(build_event_wish_card(e, lang))
            cards.append(build_event_info_card(e, lang))
            break  # first relevant event only

    return cards

# ===============================
# CARD BUILDERS
# ===============================

def build_good_morning_card(panchang):
    try:
        abhijit = panchang.get("abhijit_muhurta", {})
        rahu = panchang.get("rahu_kaal", {})

        a_start = abhijit.get("start", "")
        a_end = abhijit.get("end", "")

        r_start = rahu.get("start", "")
        r_end = rahu.get("end", "")

        # 🔹 English content
        content_en = (
            f"Good Morning ✨\n"
            f"Have a शुभ day.\n\n"
            f"🌼 Auspicious time today: {a_start} to {a_end} (Abhijit Muhurta)\n"
            f"⚠️ Rahu Kaal: {r_start} to {r_end} — avoid starting new work."
        )

        # 🔹 Hindi content
        content_hi = (
            f"सुप्रभात ✨\n"
            f"आपका दिन शुभ हो।\n\n"
            f"🌼 आज का शुभ समय: {a_start} से {a_end} (अभिजीत मुहूर्त)\n"
            f"⚠️ राहु काल: {r_start} से {r_end} — इस दौरान नए काम से बचें।"
        )

        return {
            "type": "good_morning",
            "design_type": CARD_DESIGN_MAP.get("good_morning"),
            "title_en": "Good Morning ✨",
            "title_hi": "सुप्रभात ✨",
            "content_en": content_en,
            "content_hi": content_hi,
            "meta": {
                "abhijit": f"{a_start} - {a_end}",
                "rahu_kaal": f"{r_start} - {r_end}"
            }
        }

    except Exception:
        return {
            "type": "good_morning",
            "design_type": CARD_DESIGN_MAP.get("good_morning"),
            "title_en": "Good Morning",
            "title_hi": "सुप्रभात",
            "content_en": "Panchang not available.",
            "content_hi": "पंचांग उपलब्ध नहीं है।",
            "meta": {}
        }
    
def build_chaughadiya_card(panchang):
    try:
        chaughadiya = panchang.get("chaughadiya", {})
        day_slots = chaughadiya.get("day", [])

        shubh_slots = []
        ashubh_slots = []

        # 🔹 classify slots
        for slot in day_slots:
            start = slot.get("start")
            end = slot.get("end")
            name = slot.get("name_en")

            if slot.get("nature") == "shubh":
                shubh_slots.append(f"{name} ({start}-{end})")
            else:
                ashubh_slots.append(f"{name} ({start}-{end})")

        # 🔹 pick highlights
        best_time = shubh_slots[0] if shubh_slots else "N/A"
        avoid_time = ashubh_slots[0] if ashubh_slots else "N/A"

        # 🔹 English content
        content_en = (
            f"Today’s best time: {best_time}\n"
            f"Avoid this time: {avoid_time}"
        )

        # 🔹 Hindi content
        content_hi = (
            f"आज का शुभ समय: {best_time}\n"
            f"इस समय से बचें: {avoid_time}"
        )

        return {
            "type": "chaughadiya",
            "design_type": CARD_DESIGN_MAP.get("chaughadiya"),
            "title_en": "Today's Muhurat",
            "title_hi": "आज का मुहूर्त",
            "content_en": content_en,
            "content_hi": content_hi,
            "meta": {
                "best_time": best_time,
                "avoid_time": avoid_time
            }
        }

    except Exception:
        return {
            "type": "chaughadiya",
            "design_type": CARD_DESIGN_MAP.get("chaughadiya"),
            "title_en": "Today's Muhurat",
            "title_hi": "आज का मुहूर्त",
            "content_en": "Data not available.",
            "content_hi": "डेटा उपलब्ध नहीं है।",
            "meta": {}
        }
    
def build_panchak_card(panchang):
    try:
        panchak = panchang.get("panchak", {})
        is_active = panchak.get("active", False)

        if is_active:
            nakshatra = panchak.get("nakshatra", "")

            # 🔹 English
            content_en = (
                f"⚠️ Panchak is active today.\n"
                f"Nakshatra: {nakshatra}\n"
                f"Avoid construction, travel, and important decisions."
            )

            # 🔹 Hindi
            content_hi = (
                f"⚠️ आज पंचक काल सक्रिय है।\n"
                f"नक्षत्र: {nakshatra}\n"
                f"निर्माण, यात्रा और महत्वपूर्ण कार्यों से बचें।"
            )

        else:
            # 🔹 English
            content_en = (
                "✅ No Panchak today.\n"
                "You can proceed with important tasks without worry."
            )

            # 🔹 Hindi
            content_hi = (
                "✅ आज पंचक नहीं है।\n"
                "आप महत्वपूर्ण कार्य निःसंकोच कर सकते हैं।"
            )

        return {
            "type": "panchak",
            "design_type": CARD_DESIGN_MAP.get("panchak"),
            "title_en": "Panchak Alert",
            "title_hi": "पंचक सूचना",
            "content_en": content_en,
            "content_hi": content_hi,
            "meta": {
                "active": is_active
            }
        }

    except Exception:
        return {
            "type": "panchak",
            "design_type": CARD_DESIGN_MAP.get("panchak"),
            "title_en": "Panchak Alert",
            "title_hi": "पंचक सूचना",
            "content_en": "Data not available.",
            "content_hi": "डेटा उपलब्ध नहीं है।",
            "meta": {}
        }
    
def build_tomorrow_card(panchang_next):
    try:
        abhijit = panchang_next.get("abhijit_muhurta", {})

        start = abhijit.get("start", "")
        end = abhijit.get("end", "")

        # 🔹 English
        content_en = (
            f"Plan your tomorrow wisely ✨\n\n"
            f"Auspicious time: {start} to {end} (Abhijit Muhurta)\n"
            f"Check and plan your important work accordingly."
        )

        # 🔹 Hindi
        content_hi = (
            f"कल की योजना अभी बनाएं ✨\n\n"
            f"शुभ समय: {start} से {end} (अभिजीत मुहूर्त)\n"
            f"अपने महत्वपूर्ण कार्य इसी अनुसार तय करें।"
        )

        return {
            "type": "tomorrow",
            "design_type": CARD_DESIGN_MAP.get("tomorrow"),
            "title_en": "Tomorrow's Muhurat",
            "title_hi": "कल का मुहूर्त",
            "content_en": content_en,
            "content_hi": content_hi,
            "meta": {
                "abhijit": f"{start} - {end}"
            }
        }

    except Exception:
        return {
            "type": "tomorrow",
            "design_type": CARD_DESIGN_MAP.get("tomorrow"),
            "title_en": "Tomorrow's Muhurat",
            "title_hi": "कल का मुहूर्त",
            "content_en": "Data not available.",
            "content_hi": "डेटा उपलब्ध नहीं है।",
            "meta": {}
        }
    
def build_festival_card(events):
    try:
        # 🔹 pick today's festival
        festival = None
        for e in events:
            if e.get("type") in ["festival", "vrat"]:
                festival = e
                break

        if not festival:
            return None  # no card if no festival

        name = festival.get("name", "Festival")

        # 🔹 simple rule-based content (starter version)
        # later DB/meta se dynamic karenge
        if "Purnima" in name:
            content_en = (
                f"Today is {name} 🌕\n"
                f"If not fasting, light a diya in the evening and offer prayers.\n"
                f"Share this with your family 🙏"
            )

            content_hi = (
                f"आज {name} है 🌕\n"
                f"यदि व्रत नहीं रख रहे हैं, तो शाम को दीपक जलाकर प्रार्थना करें।\n"
                f"इसे अपने परिवार के साथ साझा करें 🙏"
            )

        elif "Ekadashi" in name:
            content_en = (
                f"Today is {name} 🌿\n"
                f"Avoid tamasic food and focus on light, satvik habits.\n"
                f"Spread this awareness 🙏"
            )

            content_hi = (
                f"आज {name} है 🌿\n"
                f"तामसिक भोजन से बचें और सात्विक आहार अपनाएं।\n"
                f"इस जानकारी को साझा करें 🙏"
            )

        else:
            content_en = (
                f"Today is {name} ✨\n"
                f"Take a moment for gratitude and prayer.\n"
                f"Share this with your loved ones 🙏"
            )

            content_hi = (
                f"आज {name} है ✨\n"
                f"कृतज्ञता और प्रार्थना के लिए समय निकालें।\n"
                f"इसे अपने प्रियजनों के साथ साझा करें 🙏"
            )

        return {
            "type": "festival",
            "design_type": CARD_DESIGN_MAP.get("festival"),
            "title_en": f"{name} Today",
            "title_hi": f"आज {name}",
            "content_en": content_en,
            "content_hi": content_hi,
            "meta": {
                "festival_name": name
            }
        }

    except Exception:
        return None


def build_planet_card(events):
    try:
        # 🔹 transit event pick karo
        planet_event = None
        for e in events:
            if e.get("type") == "transit":
                planet_event = e
                break

        if not planet_event:
            return None

        name = planet_event.get("name", "Planet Transit")

        # 🔹 simple parsing (starter)
        # Example: "Venus enters Taurus"
        planet = name.split(" ")[0] if name else "Planet"

        # 🔹 English
        content_en = (
            f"A major planetary shift is happening ✨\n\n"
            f"{name}\n"
            f"This change may impact love, finances, and emotions.\n\n"
            f"Everyone will feel it differently — share this and see who benefits the most 👀"
        )

        # 🔹 Hindi
        content_hi = (
            f"एक बड़ा ग्रह परिवर्तन हो रहा है ✨\n\n"
            f"{name}\n"
            f"इसका प्रभाव प्रेम, धन और भावनाओं पर पड़ सकता है।\n\n"
            f"हर व्यक्ति पर इसका असर अलग होगा — इसे साझा करें और देखें किसे सबसे अधिक लाभ होगा 👀"
        )

        return {
            "type": "planet",
            "design_type": CARD_DESIGN_MAP.get("planet"),
            "title_en": f"{planet} Transit Alert",
            "title_hi": f"{planet} गोचर अलर्ट",
            "content_en": content_en,
            "content_hi": content_hi,
            "meta": {
                "event_name": name
            }
        }

    except Exception:
        return None
    
def get_remedy_for_today(panchang):
    weekday = panchang.get("weekday", "").lower()

    matches = [r for r in REMEDY_DATA if r["day"] == weekday]

    if not matches:
        return None

    return random.choice(matches)

def build_deep_remedy_card(panchang, lang="hi"):
    data = get_remedy_for_today(panchang)

    if not data:
        return None

    if lang == "hi":
        content = (
            f"वैदिक ज्योतिष के अनुसार\n"
            f"{data['problem_hi']} की समस्या\n"
            f"{data['planet']} के कारण होती है\n\n"
            f"✨ समाधान:\n"
            f"अगले {data['duration']} {data['day']} तक:\n"
            f"{data['remedy_hi']}\n\n"
            f"इस उपाय को नियमित करने से\n"
            f"समस्या धीरे-धीरे समाप्त होती है\n\n"
            f"इसे आगे जरूर साझा करें 🙏"
        )
    else:
        content = (
            f"According to Vedic astrology,\n"
            f"{data['problem_en']} is caused by {data['planet']}.\n\n"
            f"✨ Solution:\n"
            f"For next {data['duration']} {data['day']}s:\n"
            f"{data['remedy_en']}\n\n"
            f"This remedy gradually resolves the issue.\n\n"
            f"Share this with others 🙏"
        )

    return {
        "type": "deep_remedy",
        "design_type": "minimal",
        "title_hi": "ज्योतिष उपाय",
        "title_en": "Astro Remedy",
        "content_hi": content if lang == "hi" else None,
        "content_en": content if lang == "en" else None,
        "meta": {
            "planet": data["planet"],
            "day": data["day"]
        }
    }

def build_event_wish_card(event, lang="en"):
    name_en = event.get("name_en") or event.get("name") or "Festival"
    name_hi = event.get("name_hi") or name_en

    if lang == "hi":
        content = (
            f"✨ {name_hi} की हार्दिक शुभकामनाएँ\n"
            f"आपके जीवन में सुख, समृद्धि और शांति आए 🙏\n"
            f"इसे अपने प्रियजनों के साथ साझा करें"
        )
        title_hi = f"{name_hi} शुभकामनाएँ"
        title_en = f"{name_en} Wishes"
    else:
        content = (
            f"✨ Warm wishes on {name_en}\n"
            f"May this day bring peace, prosperity and positivity 🙏\n"
            f"Share this with your loved ones"
        )
        title_en = f"{name_en} Wishes"
        title_hi = f"{name_hi} शुभकामनाएँ"

    return {
        "type": "event_wish",
        "design_type": "festival",
        "title_en": title_en,
        "title_hi": title_hi,
        "content_en": content if lang == "en" else None,
        "content_hi": content if lang == "hi" else None,
        "meta": {"event": name_en}
    }


def build_event_info_card(event, lang="en"):
    name_en = event.get("name_en") or event.get("name") or "Festival"
    name_hi = event.get("name_hi") or name_en

    # 🔥 simple rule-based (real, not dummy)
    en = "Take a moment for prayer and set a positive intention today."
    hi = "आज प्रार्थना करें और सकारात्मक संकल्प लें।"

    if "Purnima" in name_en:
        en = "Light a diya in the evening and practice gratitude."
        hi = "शाम को दीपक जलाएं और कृतज्ञता व्यक्त करें।"
    elif "Ekadashi" in name_en:
        en = "Follow a light satvik diet and avoid tamasic food."
        hi = "सात्विक आहार लें और तामसिक भोजन से बचें।"
    elif "Amavasya" in name_en:
        en = "Offer water and remember ancestors with respect."
        hi = "पितरों का स्मरण करें और जल अर्पित करें।"

    return {
        "type": "event_info",
        "design_type": "festival",
        "title_en": f"{name_en} Guide",
        "title_hi": f"{name_hi} जानकारी",
        "content_en": en if lang == "en" else None,
        "content_hi": hi if lang == "hi" else None,
        "meta": {"event": name_en}
    }
