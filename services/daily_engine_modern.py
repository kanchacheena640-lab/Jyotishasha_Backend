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
# PLANET → CATEGORY MAPPING (placeholder)
# Will update in next step
# -----------------------------------------------------
PLANET_CATEGORY_MAP = {
    "venus": "emotional_memory",
    "mercury": "overthinking",
    "mars": "conflict",
    "saturn": "health",
    "jupiter": "financial",      # placeholder
    "rahu": "confusion",         # placeholder
    "ketu": "isolation"          # placeholder
}


# -----------------------------------------------------
# MAIN ENGINE FUNCTION
# -----------------------------------------------------
def generate_modern_daily(moon_house, aspects, lang="en"):
    """
    moon_house : 1–12
    aspects    : list → ["venus", "saturn"] etc.
    lang       : "en" or "hi"
    """

    # ---------------------------
    # 1) MOOD (always present)
    # ---------------------------
    mood_line = base["mood"][str(moon_house)][lang]

    # ---------------------------
    # 2) ENERGY
    # ---------------------------
    energy_line = base["energy"][str(moon_house)][lang]

    # ---------------------------
    # 3) SPECIFIC ALERT
    # ---------------------------
    if aspects:
        planet = aspects[0].lower()     # highest priority aspect
        category = PLANET_CATEGORY_MAP.get(planet, None)
    else:
        category = None

    if category:
        alert_line = base["alert_categories"][category][lang]
    else:
        alert_line = ""   # optional
        

    # ---------------------------
    # 4) TIP based on category
    # ---------------------------
    if category:
        tip_line = base["tips"][category][lang]
    else:
        tip_line = base["tips"]["emotional_memory"][lang]  # safe fallback

    # ---------------------------
    # FINAL OUTPUT PACK
    # ---------------------------
    return {
        "mood": mood_line,
        "energy": energy_line,
        "alert": alert_line,
        "tip": tip_line
    }
