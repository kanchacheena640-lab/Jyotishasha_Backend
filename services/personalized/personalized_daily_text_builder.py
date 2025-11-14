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
# 1) MAIN TRANSIT SENTENCE
# ---------------------------------------------------------
def build_transit_sentence(today):
    nak = today["moon"]["nakshatra"]
    house = str(today["moon"]["house"])

    trait = moon_master["nakshatra_traits"].get(nak, "")
    action = random.choice(moon_master["action_words"])
    theme = moon_master["house_themes"].get(house, "")

    return f"{trait} {action} {theme}.".strip()


# ---------------------------------------------------------
# 2) ASPECT SENTENCE
# ---------------------------------------------------------
def build_aspect_sentence(today):
    aspecting = []

    for name, pdata in today["planets"].items():
        if pdata.get("aspect_on_moon") or pdata.get("conjunction_with_moon"):
            aspecting.append(name.lower())

    if not aspecting:
        return ""

    planet = random.choice(aspecting)
    key = f"{planet}_aspect_lines_en"

    if key not in aspect_master:
        return ""

    moon_house = str(today["moon"]["house"])
    return aspect_master[key].get(moon_house, "").strip()


# ---------------------------------------------------------
# 3) REMEDY / TIP LINE
# ---------------------------------------------------------
def build_remedy_sentence(today):
    house = str(today["moon"]["house"])
    tips = house_tips.get(house, [])

    if not tips:
        return ""

    return random.choice(tips).strip()
