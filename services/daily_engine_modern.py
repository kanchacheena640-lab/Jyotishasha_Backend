import json
import os


# -----------------------------------------------------
# LOAD BASE ENGINE DATA
# -----------------------------------------------------
def load_base():
    base_path = os.path.join("data", "daily_engine_base.json")
    with open(base_path, "r", encoding="utf-8") as f:
        return json.load(f)


base = load_base()


# -----------------------------------------------------
# MAIN ENGINE FUNCTION (FINAL VERSION)
# -----------------------------------------------------
def generate_modern_daily(moon_house, aspects, lang="en"):
    """
    moon_house : 1–12
    aspects    : list → ["venus", "saturn"] etc.
    lang       : "en" or "hi"
    """

    # 1) MOOD
    mood_line = base["mood"][str(moon_house)][lang]

    # 2) ENERGY
    energy_line = base["energy"][str(moon_house)][lang]

    # -------------------------------
    # 3) ALERT + TIP (Planet–House)
    # -------------------------------
    alert_line = ""
    tip_line = base["tips"]["emotional_memory"][lang]  # safe default

    if aspects:
        planet = aspects[0].lower()   # pick highest priority planet

        planet_block = base["planet_house_alert"].get(planet, {})
        house_block = planet_block.get(str(moon_house))

        if house_block:
            category = house_block["category"]
            alert_line = house_block[lang]  # custom bilingual text
            tip_line = base["tips"][category][lang]

    # -------------------------------
    # FINAL OUTPUT
    # -------------------------------
    return {
        "mood": mood_line,
        "energy": energy_line,
        "alert": alert_line,
        "tip": tip_line
    }

