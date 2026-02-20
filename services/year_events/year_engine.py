from datetime import date, timedelta
from services.panchang_engine import calculate_panchang


def calculate_event_for_year(year, lat, lon, builder_function, language="en"):

    start_date = date(year, 1, 1)
    end_date = date(year, 12, 31)

    results = []
    seen_dates = set()
    seen_month_paksha = set()

    current = start_date

    while current <= end_date:

        panchang = calculate_panchang(current, lat, lon, language)
        event = builder_function(panchang, lat, lon, language)

        if event:
            vrat_date = event.get("vrat_date")

            # Safety checks
            tithi_info = event.get("tithi", {})
            month = tithi_info.get("month")
            paksha = tithi_info.get("paksha")

            month_key = (month, paksha)

            # Prevent duplicate date + duplicate lunar slot
            if (
                vrat_date
                and vrat_date not in seen_dates
                and month_key not in seen_month_paksha
            ):
                seen_dates.add(vrat_date)
                seen_month_paksha.add(month_key)
                results.append(event)

                # 🔥 Smart lunar jump (~Ekadashi cycle)
                current += timedelta(days=13)
                continue

        current += timedelta(days=1)

    return sorted(results, key=lambda x: x["vrat_date"])