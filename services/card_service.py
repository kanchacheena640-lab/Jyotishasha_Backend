from services.card_config import CARD_DESIGN_MAP
import json
import os
import random


BASE_DIR = os.path.dirname(__file__)

with open(os.path.join(BASE_DIR, "remedy_data.json"), "r", encoding="utf-8") as f:
    REMEDY_DATA = json.load(f)["remedies"]

def generate_cards(panchang_data, events, slot="morning"):
    cards = []

    lang = panchang_data["selected_date"].get("language", "en")

    VALID_EVENT_TYPES = {"festival", "vrat"}

    # 🔥 EVENT (only once, slot based)
    for e in events:
        if e.get("type") in VALID_EVENT_TYPES:

            if slot == "evening":
                cards.append(build_festival_card(e))

            elif slot == "morning":
                cards.append(build_event_wish_card(e, lang))
                cards.append(build_event_info_card(e, lang))

            break

    # 🔥 PANCHANG CARDS
    cards.append(build_good_morning_card(panchang_data["selected_date"]))
    cards.append(build_chaughadiya_card(panchang_data["selected_date"]))
    cards.append(build_panchak_card(panchang_data["selected_date"]))
    cards.append(build_tomorrow_card(panchang_data["next_date"]))

    # 🔥 PLANET
    planet_card = build_planet_card(events)
    if planet_card:
        cards.append(planet_card)

    # 🔥 REMEDY
    remedy_card = build_deep_remedy_card(panchang_data["selected_date"], lang=lang)
    if remedy_card:
        cards.append(remedy_card)

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

        # 🔥 Safe text handling
        a_text = f"{a_start} to {a_end}" if a_start and a_end else "Not available"
        r_text = f"{r_start} to {r_end}" if r_start and r_end else "Not available"

        # 🔹 English content
        content_en = (
            f"Good Morning ✨\n"
            f"Have a blessed day.\n\n"
            f"🌼 Auspicious time today: {a_text} (Abhijit Muhurta)\n"
            f"⚠️ Rahu Kaal: {r_text} — avoid starting new work."
        )

        # 🔹 Hindi content
        content_hi = (
            f"सुप्रभात ✨\n"
            f"आपका दिन शुभ हो।\n\n"
            f"🌼 आज का शुभ समय: {a_text} (अभिजीत मुहूर्त)\n"
            f"⚠️ राहु काल: {r_text} — इस दौरान नए काम से बचें।"
        )

        return {
            "type": "good_morning",
            "design_type": CARD_DESIGN_MAP.get("good_morning"),
            "title_en": "Good Morning ✨",
            "title_hi": "सुप्रभात ✨",
            "content_en": content_en,
            "content_hi": content_hi,
            "meta": {
                "abhijit": a_text,
                "rahu_kaal": r_text
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
        # 🔹 Extract chaughadiya data
        chaughadiya = panchang.get("chaughadiya", {})
        day_slots = chaughadiya.get("day", [])

        shubh_slots = []
        ashubh_slots = []

        # 🔹 Loop through all slots and classify into shubh / ashubh
        for slot in day_slots:
            start = slot.get("start", "")
            end = slot.get("end", "")
            name_en = slot.get("name_en", "Slot")

            # 🔥 Safe formatting (avoid None-None issue)
            time_text = f"{name_en} ({start}-{end})" if start and end else name_en

            if slot.get("nature") == "shubh":
                shubh_slots.append(time_text)
            else:
                ashubh_slots.append(time_text)

        # 🔹 Pick best and avoid time (first available)
        best_time = shubh_slots[0] if shubh_slots else "Not available"
        avoid_time = ashubh_slots[0] if ashubh_slots else "Not available"

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

            # 🔹 Titles
            "title_en": "Today's Muhurat",
            "title_hi": "आज का मुहूर्त",

            # 🔹 Main content
            "content_en": content_en,
            "content_hi": content_hi,

            # 🔹 Meta data (used for UI / analytics / share cards)
            "meta": {
                "best_time": best_time,
                "avoid_time": avoid_time,
                "total_slots": len(day_slots)
            }
        }

    except Exception:
        # 🔥 Fallback (safe card if anything fails)
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
        # 🔹 Extract panchak data
        panchak = panchang.get("panchak", {})
        is_active = panchak.get("active", False)
        nakshatra = panchak.get("nakshatra", "")

        # 🔥 Safe nakshatra handling
        nakshatra_text = nakshatra if nakshatra else "Not available"

        if is_active:
            # 🔹 English content (active case)
            content_en = (
                f"⚠️ Panchak is active today.\n"
                f"Nakshatra: {nakshatra_text}\n"
                f"Avoid construction, travel, and important decisions."
            )

            # 🔹 Hindi content (active case)
            content_hi = (
                f"⚠️ आज पंचक काल सक्रिय है।\n"
                f"नक्षत्र: {nakshatra_text}\n"
                f"निर्माण, यात्रा और महत्वपूर्ण कार्यों से बचें।"
            )

        else:
            # 🔹 English content (inactive case)
            content_en = (
                "✅ No Panchak today.\n"
                "You can proceed with important tasks without worry."
            )

            # 🔹 Hindi content (inactive case)
            content_hi = (
                "✅ आज पंचक नहीं है।\n"
                "आप महत्वपूर्ण कार्य निःसंकोच कर सकते हैं।"
            )

        return {
            "type": "panchak",
            "design_type": CARD_DESIGN_MAP.get("panchak"),

            # 🔹 Titles
            "title_en": "Panchak Alert",
            "title_hi": "पंचक सूचना",

            # 🔹 Main content
            "content_en": content_en,
            "content_hi": content_hi,

            # 🔹 Meta data (useful for UI / filtering)
            "meta": {
                "active": is_active,
                "nakshatra": nakshatra_text
            }
        }

    except Exception:
        # 🔥 Fallback safe card
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
    
def build_festival_card(event):
    try:
        # 🔹 Single event expected (not list)
        if not event:
            return None

        name_en = event.get("name_en") or event.get("name") or "Festival"
        name_hi = event.get("name_hi") or name_en

        # 🔥 Normalize name (case safe)
        name_check = name_en.lower()

        # 🔹 Rule-based content (evening prep tone)
        if "purnima" in name_check:
            content_en = (
                f"{name_en} is coming 🌕\n"
                f"Prepare for evening prayers and light a diya.\n"
                f"Plan your rituals in advance 🙏"
            )

            content_hi = (
                f"{name_hi} आने वाला है 🌕\n"
                f"शाम की पूजा और दीपक के लिए तैयारी करें।\n"
                f"अपने कार्य पहले से योजना बनाएं 🙏"
            )

        elif "ekadashi" in name_check:
            content_en = (
                f"{name_en} is tomorrow 🌿\n"
                f"Prepare for fasting and follow satvik habits.\n"
                f"Avoid tamasic food from tonight 🙏"
            )

            content_hi = (
                f"{name_hi} कल है 🌿\n"
                f"व्रत की तैयारी करें और सात्विक आहार अपनाएं।\n"
                f"आज रात से तामसिक भोजन से बचें 🙏"
            )

        else:
            content_en = (
                f"{name_en} is coming ✨\n"
                f"Take time to prepare and plan your rituals.\n"
                f"Stay mindful and positive 🙏"
            )

            content_hi = (
                f"{name_hi} आने वाला है ✨\n"
                f"पूजा और कार्यों की तैयारी करें।\n"
                f"सकारात्मक और सजग रहें 🙏"
            )

        return {
            "type": "festival",
            "design_type": CARD_DESIGN_MAP.get("festival"),

            # 🔹 Titles
            "title_en": f"{name_en} Tomorrow",
            "title_hi": f"{name_hi} कल",

            # 🔹 Content
            "content_en": content_en,
            "content_hi": content_hi,

            # 🔹 Meta
            "meta": {
                "event": name_en,
                "category": "festival_prep"
            }
        }

    except Exception:
        return None


def build_planet_card(events):
    try:
        # 🔹 Find first transit-type event
        planet_event = None
        for e in events:
            if e.get("type") in ["transit"]:   # future safe
                planet_event = e
                break

        if not planet_event:
            return None

        # 🔹 Extract names safely (EN + HI)
        name_en = planet_event.get("name_en") or planet_event.get("name") or "Planet Transit"
        name_hi = planet_event.get("name_hi") or name_en

        # 🔹 Extract planet name (safe parsing)
        planet = name_en.split(" ")[0] if name_en else "Planet"

        # 🔹 English content
        content_en = (
            f"A major planetary shift is happening ✨\n\n"
            f"{name_en}\n"
            f"This change may influence love, finances, and emotions.\n\n"
            f"Check your personalized impact in the app 👀"
        )

        # 🔹 Hindi content
        content_hi = (
            f"एक महत्वपूर्ण ग्रह परिवर्तन हो रहा है ✨\n\n"
            f"{name_hi}\n"
            f"इसका प्रभाव प्रेम, धन और भावनाओं पर पड़ सकता है।\n\n"
            f"अपना व्यक्तिगत प्रभाव जानने के लिए ऐप देखें 👀"
        )

        return {
            "type": "planet",
            "design_type": CARD_DESIGN_MAP.get("planet"),

            # 🔹 Titles
            "title_en": f"{planet} Transit Alert",
            "title_hi": f"{planet} गोचर अलर्ट",

            # 🔹 Content
            "content_en": content_en,
            "content_hi": content_hi,

            # 🔹 Meta (useful for tracking / routing)
            "meta": {
                "event": name_en,
                "planet": planet,
                "category": "transit"
            }
        }

    except Exception:
        return None
    
def get_remedy_for_today(panchang):
    try:
        # 🔹 Get weekday safely (lowercase for matching)
        weekday = (panchang.get("weekday") or "").strip().lower()

        if not weekday:
            return None  # no weekday → no remedy

        # 🔹 Match remedies (case-insensitive safe)
        matches = [
            r for r in REMEDY_DATA
            if (r.get("day") or "").strip().lower() == weekday
        ]

        if not matches:
            return None  # no matching remedy

        # 🔹 Return one random remedy (variation)
        return random.choice(matches)

    except Exception:
        return None  # safe fallback

def build_deep_remedy_card(panchang, lang="hi"):
    try:
        # 🔹 Get today's remedy
        data = get_remedy_for_today(panchang)
        if not data:
            return None

        # 🔹 Safe extraction
        problem_hi = data.get("problem_hi", "")
        problem_en = data.get("problem_en", "")
        remedy_hi = data.get("remedy_hi", "")
        remedy_en = data.get("remedy_en", "")
        planet = data.get("planet", "Planet")
        duration = data.get("duration", "")
        day = data.get("day", "")

        # 🔹 Hindi content
        content_hi = (
            f"वैदिक ज्योतिष के अनुसार\n"
            f"{problem_hi} की समस्या\n"
            f"{planet} के कारण होती है\n\n"
            f"✨ समाधान:\n"
            f"अगले {duration} {day} तक:\n"
            f"{remedy_hi}\n\n"
            f"इस उपाय को नियमित करने से\n"
            f"समस्या धीरे-धीरे समाप्त होती है\n\n"
            f"इसे आगे जरूर साझा करें 🙏"
        )

        # 🔹 English content
        content_en = (
            f"According to Vedic astrology,\n"
            f"{problem_en} is caused by {planet}.\n\n"
            f"✨ Solution:\n"
            f"For next {duration} {day}s:\n"
            f"{remedy_en}\n\n"
            f"This remedy gradually resolves the issue.\n\n"
            f"Share this with others 🙏"
        )

        return {
            "type": "deep_remedy",

            # 🔥 fallback-safe (no null issue)
            "design_type": CARD_DESIGN_MAP.get("deep_remedy", "minimal"),

            "title_hi": "ज्योतिष उपाय",
            "title_en": "Astro Remedy",

            # 🔥 ALWAYS send both (UI safe)
            "content_hi": content_hi,
            "content_en": content_en,

            "meta": {
                "planet": planet,
                "day": day,
                "duration": duration,
                "category": "remedy"
            }
        }

    except Exception:
        return None

def build_event_wish_card(event, lang="en"):
    try:
        # 🔹 Safe name extraction (EN + HI)
        name_en = event.get("name_en") or event.get("name") or "Festival"
        name_hi = event.get("name_hi") or name_en

        # 🔹 Hindi content
        content_hi = (
            f"✨ {name_hi} की हार्दिक शुभकामनाएँ\n"
            f"आपके जीवन में सुख, समृद्धि और शांति आए 🙏\n"
            f"इसे अपने प्रियजनों के साथ साझा करें"
        )

        # 🔹 English content
        content_en = (
            f"✨ Warm wishes on {name_en}\n"
            f"May this day bring peace, prosperity and positivity 🙏\n"
            f"Share this with your loved ones"
        )

        return {
            "type": "event_wish",

            # 🔥 use config (not hardcoded)
            "design_type": CARD_DESIGN_MAP.get("festival"),

            # 🔹 Titles
            "title_en": f"{name_en} Wishes",
            "title_hi": f"{name_hi} शुभकामनाएँ",

            # 🔹 Content (language switch)
            "content_en": content_en if lang == "en" else None,
            "content_hi": content_hi if lang == "hi" else None,

            # 🔹 Meta (future use)
            "meta": {
                "event": name_en,
                "category": "wish"
            }
        }

    except Exception:
        return None

def build_event_info_card(event, lang="en"):
    try:
        # 🔹 Safe name extraction
        name_en = event.get("name_en") or event.get("name") or "Festival"
        name_hi = event.get("name_hi") or name_en

        name_check = name_en.lower()

        # 🔥 Default guidance
        content_en = "Take a moment for prayer and set a positive intention today."
        content_hi = "आज प्रार्थना करें और सकारात्मक संकल्प लें।"

        # 🔹 Rule-based logic (case-insensitive)
        if "purnima" in name_check:
            content_en = "Light a diya in the evening and practice gratitude."
            content_hi = "शाम को दीपक जलाएं और कृतज्ञता व्यक्त करें।"

        elif "ekadashi" in name_check:
            content_en = "Follow a light satvik diet and avoid tamasic food."
            content_hi = "सात्विक आहार लें और तामसिक भोजन से बचें।"

        elif "amavasya" in name_check:
            content_en = "Offer water and remember ancestors with respect."
            content_hi = "पितरों का स्मरण करें और जल अर्पित करें।"

        return {
            "type": "event_info",

            # 🔥 config-based design
            "design_type": CARD_DESIGN_MAP.get("festival"),

            # 🔹 Titles
            "title_en": f"{name_en} Guide",
            "title_hi": f"{name_hi} जानकारी",

            # 🔹 Content (language-based)
            "content_en": content_en if lang == "en" else None,
            "content_hi": content_hi if lang == "hi" else None,

            # 🔹 Meta (future use)
            "meta": {
                "event": name_en,
                "category": "info"
            }
        }

    except Exception:
        return None
