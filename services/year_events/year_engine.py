from datetime import date, timedelta
from services.panchang_engine import calculate_panchang


def calculate_event_for_year(year, lat, lon, builder_function, language="en"):

    start_date = date(year, 1, 1)
    end_date = date(year, 12, 31)

    results = []
    current = start_date

    while current <= end_date:

        panchang = calculate_panchang(current, lat, lon, language)

        event_data = builder_function(panchang, lat, lon, language)

        if event_data:
            results.append(event_data)

        current += timedelta(days=1)

    return results