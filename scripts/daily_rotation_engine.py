import json
import os
from flask import Blueprint, request, jsonify

daily_bp = Blueprint("daily_bp", __name__)

# Paths
POOL_PATH = "C:/jyotishasha_backend/data/daily_pool.json"
OUTPUT_PATH = "C:/jyotishasha_backend/data/daily_fixed.json"
COUNTER_PATH = "C:/jyotishasha_backend/data/daily_counter.txt"

# Zodiac order
ZODIACS = [
    "aries", "taurus", "gemini", "cancer", "leo", "virgo",
    "libra", "scorpio", "sagittarius", "capricorn", "aquarius", "pisces"
]

# Load content pool
with open(POOL_PATH, "r", encoding="utf-8") as f:
    pool_data = json.load(f)

# Load current offset (or default to 0)
if os.path.exists(COUNTER_PATH):
    with open(COUNTER_PATH, "r") as f:
        start_index = int(f.read().strip())
else:
    start_index = 0

# Rotation logic (+12 each day)
entries_needed = len(ZODIACS)
rotated_data = {}
total_entries = len(pool_data)

for i, zodiac in enumerate(ZODIACS):
    index = (start_index + i) % total_entries
    rotated_data[zodiac] = pool_data[index]["daily_horoscope"]

# Save daily_fixed.json
with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(rotated_data, f, ensure_ascii=False, indent=2)

# Update rotation counter for next day
new_start_index = (start_index + 12) % total_entries
with open(COUNTER_PATH, "w") as f:
    f.write(str(new_start_index))

print("✅ daily_fixed.json generated successfully.")
