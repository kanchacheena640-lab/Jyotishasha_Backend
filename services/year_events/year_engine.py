from datetime import date, timedelta
from services.panchang_engine import calculate_panchang


def calculate_event_for_year(year, lat, lon, builder_function, language="en"):

    start_date = date(year, 1, 1)
    end_date = date(year, 12, 31)

    results = []
    seen_dates = set()

    current = start_date

    while current <= end_date:

        panchang = calculate_panchang(current, lat, lon, language)

        event_data = builder_function(panchang, lat, lon, language)

        if event_data:
            vrat_date = event_data.get("vrat_date")

            if vrat_date and vrat_date not in seen_dates:
                seen_dates.add(vrat_date)
                results.append(event_data)

        current += timedelta(days=1)

    # optional: sort just in case
    results.sort(key=lambda x: x.get("vrat_date"))

    return results