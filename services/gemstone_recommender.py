import json
import os

SIGN_LIST = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
]

PLANET_OWNERSHIP = {
    "Aries": "Mars", "Taurus": "Venus", "Gemini": "Mercury", "Cancer": "Moon",
    "Leo": "Sun", "Virgo": "Mercury", "Libra": "Venus", "Scorpio": "Mars",
    "Sagittarius": "Jupiter", "Capricorn": "Saturn", "Aquarius": "Saturn", "Pisces": "Jupiter"
}

EXALTED_SIGNS = {
    "Sun": "Aries", "Moon": "Taurus", "Mars": "Capricorn",
    "Mercury": "Virgo", "Jupiter": "Cancer", "Venus": "Pisces", "Saturn": "Libra"
}

PLANET_GEMSTONE_MAP = {
    "Sun": ("Ruby", "माणिक्य"),
    "Moon": ("Pearl", "मोती"),
    "Mars": ("Red Coral", "मूंगा"),
    "Mercury": ("Emerald", "पन्ना"),
    "Jupiter": ("Yellow Sapphire", "पुखराज"),
    "Venus": ("Diamond", "हीरा"),
    "Saturn": ("Blue Sapphire", "नीलम"),
    "Rahu": ("Hessonite", "गोमेद"),
    "Ketu": ("Cat’s Eye", "लहसुनिया")
}

PLANET_SUBSTONE_MAP = {
    "Sun": ("Garnet", "तमड़ा"),
    "Moon": ("Moonstone", "चंद्रकांत मणि"),
    "Mars": ("Carnelian", "केतकी"),
    "Mercury": ("Peridot", "ओलिवाइन"),
    "Jupiter": ("Citrine", "सुनैला"),
    "Venus": ("White Zircon", "सफेद ज़िरकन"),
    "Saturn": ("Amethyst", "कतैला"),
    "Rahu": ("Lapis Lazuli", "लाजवर्त"),
    "Ketu": ("Turquoise", "फिरोज़ा")
}

BAD_HOUSES = [6, 8, 12]
GOOD_HOUSES = [1, 4, 5, 7, 9, 10]


def get_planet_by_name(planets, name):
    for p in planets:
        if p["name"] == name:
            return p
    return None


def evaluate_strength(planet):
    score = 0
    if planet["house"] in GOOD_HOUSES:
        score += 1
    if planet["sign"] == EXALTED_SIGNS.get(planet["name"]):
        score += 1
    if planet["sign"] == planet.get("own_sign"):
        score += 1
    if planet["house"] in BAD_HOUSES:
        score -= 1
    return score


def recommend_gemstone_from_lagna_9th(lagna_sign, planets, language="en"):
    # Step 1: Lagna lord & 9th lord
    lagna_lord = PLANET_OWNERSHIP.get(lagna_sign)
    lagna_index = SIGN_LIST.index(lagna_sign)
    ninth_sign = SIGN_LIST[(lagna_index + 8) % 12]
    ninth_lord = PLANET_OWNERSHIP.get(ninth_sign)

    lagna_planet = get_planet_by_name(planets, lagna_lord)
    ninth_planet = get_planet_by_name(planets, ninth_lord)
    if not lagna_planet or not ninth_planet:
        return {"planet": None, "paragraph": "Data incomplete for recommendation."}

    # Step 2: Assign own_sign
    lagna_planet["own_sign"] = [k for k, v in PLANET_OWNERSHIP.items() if v == lagna_planet["name"]]
    ninth_planet["own_sign"] = [k for k, v in PLANET_OWNERSHIP.items() if v == ninth_planet["name"]]

    # Step 3: Score comparison
    lagna_score = evaluate_strength(lagna_planet)
    ninth_score = evaluate_strength(ninth_planet)
    final_planet = ninth_planet["name"] if ninth_score > lagna_score else lagna_planet["name"]

    # Step 4: Load JSON content
    filename = "gemstone_tool_content_hi.json" if language == "hi" else "gemstone_tool_content_en.json"
    json_path = os.path.join("data", filename)
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            content = json.load(f)
        paragraph_template = content.get("main_report", "")
        cta_block = content.get("cta", {})
    except:
        paragraph_template = "We have deeply analyzed your Kundali and found that {planet}, the most supportive and auspicious planet for you, holds the key to your growth, protection, and prosperity. Wearing its gemstone can bring lifelong benefits."
        cta_block = {}

    final_paragraph = paragraph_template.replace("{planet}", final_planet)

    # Step 5: Gemstone + Substone combo
    gem_en, gem_hi = PLANET_GEMSTONE_MAP.get(final_planet, ("", ""))
    sub_en, sub_hi = PLANET_SUBSTONE_MAP.get(final_planet, ("", ""))

    gemstone_combined = f"{gem_en} ({gem_hi})" if gem_en else ""
    substone_combined = f"{sub_en} ({sub_hi})" if sub_en else ""

    return {
        "planet": final_planet,
        "paragraph": final_paragraph,
        "gemstone": gemstone_combined,
        "substone": substone_combined,
        "cta": cta_block
    }
