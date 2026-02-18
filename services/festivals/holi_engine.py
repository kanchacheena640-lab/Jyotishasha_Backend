# services/festivals/holi_engine.py

from datetime import datetime, timedelta
from services.panchang_engine import calculate_panchang, _tithi_number_at
from services.lunar_month_engine import get_lunar_month


def detect_holi(year, lat, lon, language="en"):
    """
    Detect Holi for given year.

    Rule:
    - Phalguna Shukla Purnima at SUNSET = Holika Dahan
    - Next day = Dhulandi
    - Based strictly on Tithi at sunset (Drik method)
    """

    start_date = datetime(year, 1, 1).date()
    end_date = datetime(year, 12, 31).date()

    current_date = start_date

    while current_date <= end_date:

        panchang = calculate_panchang(
            current_date, lat, lon, language
        )

        sunset_str = panchang.get("sunset")
        weekday = panchang.get("weekday")

        if not sunset_str:
            current_date += timedelta(days=1)
            continue

        sunset_dt = datetime.strptime(
            f"{current_date} {sunset_str}",
            "%Y-%m-%d %H:%M"
        )

        # 1️⃣ Tithi at sunset
        tithi_at_sunset = _tithi_number_at(sunset_dt)

        if tithi_at_sunset != 15:
            current_date += timedelta(days=1)
            continue

        # 2️⃣ Lunar month at sunset
        lunar_month = get_lunar_month(sunset_dt)

        if lunar_month not in ("Phalguna", "फाल्गुन"):
            current_date += timedelta(days=1)
            continue

        # ✅ Valid Holika Dahan found
        holika_dahan_date = current_date
        holi_date = current_date + timedelta(days=1)

        return {
            "year": year,
            "holika_dahan": {
                "date": holika_dahan_date.strftime("%Y-%m-%d"),
                "weekday": weekday,
                "sunset_time": sunset_str,
                "tithi_at_sunset": 15,
            },
            "holi_dhulandi": {
                "date": holi_date.strftime("%Y-%m-%d"),
            }
        }

        # (Loop naturally ends after return)

    return None
