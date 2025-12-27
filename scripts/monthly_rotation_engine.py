import json
import os
from datetime import datetime

# =========================
# BASE PATH
# =========================
BASE_DIR = "C:/jyotishasha_backend/data"

POOL_EN = os.path.join(BASE_DIR, "monthly_pool.json")
POOL_HI = os.path.join(BASE_DIR, "monthly_pool_hi.json")

OUT_EN = os.path.join(BASE_DIR, "monthly_fixed.json")
OUT_HI = os.path.join(BASE_DIR, "monthly_fixed_hi.json")

COUNTER_PATH = os.path.join(BASE_DIR, "monthly_counter.txt")

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


def run_monthly_rotation():
    pool_en = load_json(POOL_EN, "monthly_pool.json")
    pool_hi = load_json(POOL_HI, "monthly_pool_hi.json")

    if len(pool_en) < ROTATION_STEP or len(pool_hi) < ROTATION_STEP:
        raise ValueError("Both monthly pools must contain at least 12 entries")

    # 🔢 Single source of truth counter
    start_index = 0
    if os.path.exists(COUNTER_PATH):
        with open(COUNTER_PATH, "r") as f:
            val = f.read().strip()
            if val.isdigit():
                start_index = int(val)

    total = min(len(pool_en), len(pool_hi))

    rotated_en = {}
    rotated_hi = {}

    # 🔁 SAME 1–12 mapping for EN + HI
    for i, zodiac in enumerate(ZODIACS):
        idx = (start_index + i) % total
        rotated_en[zodiac] = pool_en[idx]["monthly_horoscope"]
        rotated_hi[zodiac] = pool_hi[idx]["monthly_horoscope"]

    # 💾 Write fixed files
    with open(OUT_EN, "w", encoding="utf-8") as f:
        json.dump(rotated_en, f, ensure_ascii=False, indent=2)

    with open(OUT_HI, "w", encoding="utf-8") as f:
        json.dump(rotated_hi, f, ensure_ascii=False, indent=2)

    # ⏭ Update counter ONCE
    new_index = (start_index + ROTATION_STEP) % total
    with open(COUNTER_PATH, "w") as f:
        f.write(str(new_index))

    print("✅ monthly_fixed.json & monthly_fixed_hi.json updated")
    print("🔢 Counter:", new_index)
    print("🕒 Time:", datetime.now())


if __name__ == "__main__":
    run_monthly_rotation()
