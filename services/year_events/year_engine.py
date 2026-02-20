from datetime import date, timedelta
from services.panchang_engine import calculate_panchang

def calculate_event_for_year(year, lat, lon, builder_function, language="en"):

    start_date = date(year, 1, 1)
    end_date = date(year, 12, 31)

    results = []
    seen = set()
    current = start_date

    while current <= end_date:

        panchang = calculate_panchang(current, lat, lon, language)
        event = builder_function(panchang, lat, lon, language)

        if event:
            vrat_date = event.get("vrat_date")

            if vrat_date not in seen:
                seen.add(vrat_date)
                results.append(event)

                # 🔥 Jump 13 days
                current += timedelta(days=13)
                continue

        current += timedelta(days=1)

    return sorted(results, key=lambda x: x["vrat_date"])