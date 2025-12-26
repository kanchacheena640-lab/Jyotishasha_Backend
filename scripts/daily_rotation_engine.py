import json
import os
from datetime import datetime

# =========================
# BASE PATH
# =========================
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

POOL_EN = os.path.join(BASE_DIR, "data", "daily_pool.json")
POOL_HI = os.path.join(BASE_DIR, "data", "daily_pool_hi.json")

OUT_EN = os.path.join(BASE_DIR, "data", "daily_fixed.json")
OUT_HI = os.path.join(BASE_DIR, "data", "daily_fixed_hi.json")

COUNTER_PATH = os.path.join(BASE_DIR, "data", "daily_counter.txt")

ZODIACS = [
    "aries", "taurus", "gemini", "cancer", "leo", "virgo",
    "libra", "scorpio", "sagittarius", "capricorn", "aquarius", "pisces"
]

ROTATION_STEP = 12


def load_json(path, label):
    if not os.path.exists(path):
        raise FileNotFoundError(f"{label} not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_daily_rotation():
    pool_en = load_json(POOL_EN, "daily_pool.json")
    pool_hi = load_json(POOL_HI, "daily_pool_hi.json")

    if len(pool_en) < ROTATION_STEP or len(pool_hi) < ROTATION_STEP:
        raise ValueError("Both pools must contain at least 12 entries")

    # Single source of truth
    start_index = 0
    if os.path.exists(COUNTER_PATH):
        with open(COUNTER_PATH, "r") as f:
            v = f.read().strip()
            if v.isdigit():
                start_index = int(v)

    total = min(len(pool_en), len(pool_hi))

    rotated_en = {}
    rotated_hi = {}

    # SAME 1–12 mapping for EN + HI
    for i, zodiac in enumerate(ZODIACS):
        idx = (start_index + i) % total
        rotated_en[zodiac] = pool_en[idx]["daily_horoscope"]
        rotated_hi[zodiac] = pool_hi[idx]["daily_horoscope"]

    # Write outputs
    with open(OUT_EN, "w", encoding="utf-8") as f:
        json.dump(rotated_en, f, ensure_ascii=False, indent=2)

    with open(OUT_HI, "w", encoding="utf-8") as f:
        json.dump(rotated_hi, f, ensure_ascii=False, indent=2)

    # Update counter ONCE
    new_index = (start_index + ROTATION_STEP) % total
    with open(COUNTER_PATH, "w") as f:
        f.write(str(new_index))

    print("✅ daily_fixed.json & daily_fixed_hi.json updated")
    print("📁 EN:", OUT_EN)
    print("📁 HI:", OUT_HI)
    print("🔢 Counter:", new_index)
    print("🕒 Time:", datetime.now())


if __name__ == "__main__":
    run_daily_rotation()
