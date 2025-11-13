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

    house = str(moon_house)

    # ---------------------------
    # 1) MOOD (always present)
    # ---------------------------
    mood_line = base["mood"][house][lang]

    # ---------------------------
    # 2) ENERGY (always present)
    # ---------------------------
    energy_line = base["energy"][house][lang]

    # ---------------------------
    # 3) SPECIFIC ALERT (planet + house)
    # ---------------------------
    if aspects:
        # Highest priority planet = first
        planet = aspects[0].lower()

        # Check if planet-house block exists
        planet_data = base["planet_house_alert"].get(planet, {})
        house_data = planet_data.get(house)

        if house_data:
            # Direct bilingual line from planet-house table
            alert_line = house_data[lang]
            tip_line = base["tips"][house_data["category"]][lang]
        else:
            # Fallback 1 → category from alert_categories
            alert_line = ""
            tip_line = base["tips"]["emotional_memory"][lang]

    else:
        # No aspects → no alert
        alert_line = ""
        tip_line = base["tips"]["emotional_memory"][lang]

    # ---------------------------
    # FINAL OUTPUT PACK
    # ---------------------------
    return {
        "mood": mood_line,
        "energy": energy_line,
        "alert": alert_line,
        "tip": tip_line
    }
