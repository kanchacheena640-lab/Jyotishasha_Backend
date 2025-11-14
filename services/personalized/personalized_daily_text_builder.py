# personalized_daily_text_builder.py
# Builds 3-line personalized daily horoscope for Jyotishasha

import json
import random
import os

# ---------------------------------------------------------
#  Utility → Load JSON from data/personalizedData folder
# ---------------------------------------------------------
def load_json(relative_path):
    base = os.path.dirname(os.path.abspath(__file__))
    full_path = os.path.join(base, "..", "..", "data", "personalizedData", relative_path)

    with open(full_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------
#  Load all JSON data files
# ---------------------------------------------------------
moon_master = load_json("moon_transit_master.json")
aspect_master = load_json("moon_aspect_all_planets_lines.json")
house_tips = load_json("house_based_tips.json")


# ---------------------------------------------------------
# 1) MAIN TRANSIT SENTENCE (LANGUAGE SAFE)
# ---------------------------------------------------------
def build_transit_sentence(today):
    lang = today.get("lang", "en")  # en / hi

    nak = today["moon"]["nakshatra"]
    house = str(today["moon"]["house"])

    # pick correct language keys
    trait = moon_master[f"nakshatra_traits_{lang}"].get(nak, "")
    action = random.choice(moon_master[f"action_words_{lang}"])
    theme = moon_master[f"house_themes_{lang}"].get(house, "")

    return f"{trait} {action} {theme}.".strip()


# ---------------------------------------------------------
# 2) ASPECT SENTENCE (LANGUAGE SAFE)
# ---------------------------------------------------------
def build_aspect_sentence(today):
    lang = today.get("lang", "en")  # en / hi
    aspecting = []

    for name, pdata in today["planets"].items():
        if pdata.get("aspect_on_moon") or pdata.get("conjunction_with_moon"):
            aspecting.append(name.lower())

    if not aspecting:
        return ""

    planet = random.choice(aspecting)
    key = f"{planet}_aspect_lines_{lang}"

    if key not in aspect_master:
        return ""

    moon_house = str(today["moon"]["house"])
    return aspect_master[key].get(moon_house, "").strip()


# ---------------------------------------------------------
# 3) REMEDY / TIP LINE (LANGUAGE SAFE)
# ---------------------------------------------------------
def build_remedy_sentence(today):
    lang = today.get("lang", "en")  # en / hi

    house = str(today["moon"]["house"])
    tips = house_tips[f"house_based_tips_{lang}"].get(house, [])

    if not tips:
        return ""

    return random.choice(tips).strip()
