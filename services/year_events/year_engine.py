from datetime import date, timedelta
from services.panchang_engine import calculate_sunrise_sunset
from services.astro_core import _tithi_number_at


def _get_sunrise(d, lat, lon):
    ss = calculate_sunrise_sunset(d, lat, lon)

    # If tuple like (sunrise, sunset)
    if isinstance(ss, tuple):
        return ss[0]

    # If dict like {"sunrise": ..., "sunset": ...}
    return ss["sunrise"]


def calculate_event_for_year(year, lat, lon, builder_function, language="en"):

    start_date = date(year, 1, 1)
    end_date = date(year, 12, 31)

    results = []
    seen = set()
    current = start_date

    while current <= end_date:

        sunrise = _get_sunrise(current, lat, lon)
        tithi_num = _tithi_number_at(sunrise)

        # Ekadashi possible numbers
        if tithi_num in (11, 26):

            event = builder_function(current, lat, lon, language)

            if event:
                vrat_date = event.get("vrat_date")

                if vrat_date and vrat_date.startswith(str(year)):
                    if vrat_date not in seen:
                        seen.add(vrat_date)
                        results.append(event)

                        # Skip ahead to reduce heavy computation
                        current += timedelta(days=12)
                        continue

        current += timedelta(days=15)

        if len(results) >= 26:
            break

    return sorted(results, key=lambda x: x["vrat_date"])