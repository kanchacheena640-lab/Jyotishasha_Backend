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
# MAIN ENGINE FUNCTION (UPDATED PRO VERSION)
# -----------------------------------------------------
def generate_modern_daily(moon_house, aspects, lang="en"):
    """
    moon_house : 1–12
    aspects    : list → ["venus", "saturn"] etc.
    lang       : "en" or "hi"    (default: "en")
    """

    # ---------------------------------------
    # 🔥 DEBUG BLOCK — to trace real input
    # ---------------------------------------
    print("\n")
    print("═══════════════════════════════════════════")
    print("🔍 DAILY ENGINE INPUT RECEIVED")
    print("═══════════════════════════════════════════")
    print(f"📌 moon_house    → {moon_house}")
    print(f"📌 aspects       → {aspects}")
    print(f"📌 language      → {lang}")
    print("📁 Source        → generate_modern_daily()")
    print("═══════════════════════════════════════════")
    print("\n")

    # ---------------------------------------
    # SAFETY: invalid lang fallback to English
    # ---------------------------------------
    if lang not in ["en", "hi"]:
        lang = "en"

    # 1) MOOD
    mood_line = base["mood"][str(moon_house)][lang]

    # 2) ENERGY
    energy_line = base["energy"][str(moon_house)][lang]

    # 3) ALERT + TIP
    alert_line = ""
    tip_line = base["tips"]["emotional_memory"][lang]  # safe default

    if aspects:
        planet = aspects[0].lower()   # highest priority planet only

        planet_block = base["planet_house_alert"].get(planet, {})
        house_block = planet_block.get(str(moon_house))

        if house_block:
            category = house_block["category"]
            alert_line = house_block[lang]
            tip_line = base["tips"][category][lang]

    return {
        "mood": mood_line,
        "energy": energy_line,
        "alert": alert_line,
        "tip": tip_line
    }
