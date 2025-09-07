import json
import os

# Paths
POOL_PATH = "C:/jyotishasha_backend/data/monthly_pool.json"
OUTPUT_PATH = "C:/jyotishasha_backend/data/monthly_fixed.json"
COUNTER_PATH = "C:/jyotishasha_backend/data/monthly_counter.txt"

# Zodiac signs
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

# Build fixed data for this month (12 entries)
rotated_data = {}
total_entries = len(pool_data)

for i, zodiac in enumerate(ZODIACS):
    index = (start_index + i) % total_entries
    rotated_data[zodiac] = pool_data[index]["monthly_horoscope"]

# Save monthly_fixed.json
with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(rotated_data, f, ensure_ascii=False, indent=2)

# Update offset for next month
new_start_index = (start_index + 12) % total_entries
with open(COUNTER_PATH, "w") as f:
    f.write(str(new_start_index))

print("✅ monthly_fixed.json generated successfully.")
