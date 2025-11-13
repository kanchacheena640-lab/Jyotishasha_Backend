# ---------------------------------------------------------
#  DAILY HOROSCOPE GENERATOR (Moon + House + Fast Planets)
#  Jyotishasha — Final Production Version
#
#  INPUT  → user_profile {lagna, moon_rashi, nakshatra,
#                         moon_house, fast_planets, paksha}
#
#  OUTPUT → English + Hindi Daily Horoscope (Final Text)
# ---------------------------------------------------------

import json
from datetime import date
import os



# ---------------------------------------------------------
#  Utility: Load JSON safely
# ---------------------------------------------------------
def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------
#  Load Template Files
# ---------------------------------------------------------
BASE_TEMPLATE_PATH = "data/moon_daily_templates.json"
HOOK_TEMPLATE_PATH = "data/day_lord_hooks.json"

base_data = load_json(BASE_TEMPLATE_PATH)
hook_data = load_json(HOOK_TEMPLATE_PATH)


# ---------------------------------------------------------
#  Step 1 → Get Base Block for Rashi + Nakshatra
# ---------------------------------------------------------
def find_base_block(moon_rashi, nakshatra):
    for block in base_data["base_blocks"]:
        if block["moon_rashi"] == moon_rashi and block["nakshatra"] == nakshatra:
            return block
    return None



# ---------------------------------------------------------
#  Step 2 → Get House Effect
# ---------------------------------------------------------
def get_house_effect(house_number):
    return base_data["house_effect"].get(str(house_number))



# ---------------------------------------------------------
#  Step 3 → Get Fast Planet Influence
#  fast_planets = ["mercury", "venus", "mars"] (only one active)
# ---------------------------------------------------------
def get_fast_planet_effect(block, fast_planet):
    if fast_planet is None:
        return {"en": "", "hi": ""}
    
    key_en = f"{fast_planet}_en"
    key_hi = f"{fast_planet}_hi"

    return {
        "en": block["planet"].get(key_en, ""),
        "hi": block["planet"].get(key_hi, "")
    }



# ---------------------------------------------------------
#  Step 4 → Paksha Effect
# ---------------------------------------------------------
def get_paksha_effect(block, paksha):
    if paksha.lower() == "shukla":
        return {
            "en": block["paksha"]["shukla_en"],
            "hi": block["paksha"]["shukla_hi"]
        }
    else:
        return {
            "en": block["paksha"]["krishna_en"],
            "hi": block["paksha"]["krishna_hi"]
        }



# ---------------------------------------------------------
#  Step 5 → Rotate Hook Line (Day Lord Darshan)
# ---------------------------------------------------------
def get_rotating_hook():
    today = date.today().day
    idx = today % len(hook_data["hooks"])
    return hook_data["hooks"][idx]



# ---------------------------------------------------------
#  MAIN GENERATOR FUNCTION
# ---------------------------------------------------------
def generate_daily_horoscope(user_profile):
    """
    user_profile example:
    {
      "moon_rashi": "Aries",
      "nakshatra": "Ashwini",
      "moon_house": 5,
      "fast_planet": "venus",     # or mercury/mars/None
      "paksha": "Shukla"
    }
    """

    block = find_base_block(user_profile["moon_rashi"], user_profile["nakshatra"])
    house = get_house_effect(user_profile["moon_house"])
    planet = get_fast_planet_effect(block, user_profile["fast_planet"])
    paksha = get_paksha_effect(block, user_profile["paksha"])
    hook = get_rotating_hook()

    # ------------- Build English Text ----------------------
    en = (
        block["base"]["en"] + " "
        + house["en"] + " "
        + planet["en"] + " "
        + paksha["en"] + "\n\n"
        + hook["en"]
    )

    # ------------- Build Hindi Text ------------------------
    hi = (
        block["base"]["hi"] + " "
        + house["hi"] + " "
        + planet["hi"] + " "
        + paksha["hi"] + "\n\n"
        + hook["hi"]
    )

    return {"en": en.strip(), "hi": hi.strip()}



# ---------------------------------------------------------
#  TEST RUN (You can remove this during deployment)
# ---------------------------------------------------------
if __name__ == "__main__":
    sample = {
        "moon_rashi": "Aries",
        "nakshatra": "Ashwini",
        "moon_house": 5,
        "fast_planet": "venus",
        "paksha": "Shukla"
    }

    out = generate_daily_horoscope(sample)
    print("\nENGLISH:\n", out["en"])
    print("\nHINDI:\n", out["hi"])
