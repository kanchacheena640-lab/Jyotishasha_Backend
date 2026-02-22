from datetime import date, timedelta
from services.ekadashi_engine import build_ekadashi_json

lat = 26.8467
lon = 80.9462

current = date(2026, 1, 1)
end = date(2026, 12, 31)

seen = set()

while current <= end:
    result = build_ekadashi_json(current, lat, lon)

    if result:
        vrat = result["vrat_date"]

        if vrat not in seen:
            seen.add(vrat)
            print(vrat, result["name_en"])

            # ⬇ Jump ahead 10 days (avoid daily brute force)
            current += timedelta(days=10)
            continue

    current += timedelta(days=1)

print("TOTAL:", len(seen))