import json
import os
from extensions import db
from modules.daily_counter.model import DailyCounter

# =========================
# BASE PATH
# =========================
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

POOL_EN = os.path.join(BASE_DIR, "data", "daily_pool.json")
POOL_HI = os.path.join(BASE_DIR, "data", "daily_pool_hi.json")

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


def run_daily_rotation_runtime():
    pool_en = load_json(POOL_EN, "daily_pool.json")
    pool_hi = load_json(POOL_HI, "daily_pool_hi.json")

    total = min(len(pool_en), len(pool_hi))
    if total < ROTATION_STEP:
        raise ValueError("Pools must contain at least 12 entries")

    # DB = single source of truth
    counter_row = DailyCounter.query.first()
    if not counter_row:
        counter_row = DailyCounter(counter=0)
        db.session.add(counter_row)
        db.session.commit()

    start_index = counter_row.counter

    rotated_en = {}
    rotated_hi = {}

    for i, zodiac in enumerate(ZODIACS):
        idx = (start_index + i) % total
        rotated_en[zodiac] = pool_en[idx]["daily_horoscope"]
        rotated_hi[zodiac] = pool_hi[idx]["daily_horoscope"]

    # Update counter once per run
    counter_row.counter = (start_index + ROTATION_STEP) % total
    db.session.commit()

    return rotated_en, rotated_hi
