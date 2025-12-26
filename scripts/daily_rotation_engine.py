import json
import os
from datetime import datetime

# =========================
# BASE PATH (FIXED)
# =========================
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

POOL_PATH = os.path.join(BASE_DIR, "data", "daily_pool.json")
OUTPUT_PATH = os.path.join(BASE_DIR, "data", "daily_fixed.json")
COUNTER_PATH = os.path.join(BASE_DIR, "data", "daily_counter.txt")

ZODIACS = [
    "aries", "taurus", "gemini", "cancer", "leo", "virgo",
    "libra", "scorpio", "sagittarius", "capricorn", "aquarius", "pisces"
]

ROTATION_STEP = 12


def run_daily_rotation():
    if not os.path.exists(POOL_PATH):
        raise FileNotFoundError(f"daily_pool.json not found at {POOL_PATH}")

    with open(POOL_PATH, "r", encoding="utf-8") as f:
        pool_data = json.load(f)

    if len(pool_data) < ROTATION_STEP:
        raise ValueError("daily_pool.json must contain at least 12 entries")

    start_index = 0
    if os.path.exists(COUNTER_PATH):
        with open(COUNTER_PATH, "r") as f:
            val = f.read().strip()
            if val.isdigit():
                start_index = int(val)

    rotated = {}
    total = len(pool_data)

    for i, zodiac in enumerate(ZODIACS):
        idx = (start_index + i) % total
        rotated[zodiac] = pool_data[idx]["daily_horoscope"]

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(rotated, f, ensure_ascii=False, indent=2)

    new_index = (start_index + ROTATION_STEP) % total
    with open(COUNTER_PATH, "w") as f:
        f.write(str(new_index))

    print("✅ daily_fixed.json updated successfully")
    print("📁 Output:", OUTPUT_PATH)
    print("🕒 Time:", datetime.now())


if __name__ == "__main__":
    run_daily_rotation()
