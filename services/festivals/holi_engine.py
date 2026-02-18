# services/festivals/holi_engine.py

from datetime import datetime, timedelta
from services.panchang_engine import calculate_panchang, _tithi_number_at
from services.lunar_month_engine import get_lunar_month


def detect_holi(year, lat, lon, language="en"):
    """
    Detect Holi for given year.

    Rule (Drik compliant):
    - Holika Dahan = Phalguna Shukla Purnima active at SUNSET
    - Dhulandi (Rangwali Holi) = next calendar day
    - Lunar month evaluated at sunset moment
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
        tithi = panchang.get("tithi") or {}

        if not (sunset_str and tithi):
            current_date += timedelta(days=1)
            continue

        # Create sunset datetime (IST)
        sunset_dt = datetime.strptime(
            f"{current_date.strftime('%Y-%m-%d')} {sunset_str}",
            "%Y-%m-%d %H:%M"
        )

        # 1️⃣ Tithi at sunset (authoritative check)
        tithi_at_sunset = _tithi_number_at(sunset_dt)

        if tithi_at_sunset != 15:
            current_date += timedelta(days=1)
            continue

        # 2️⃣ Lunar month at sunset moment
        lunar_month = get_lunar_month(sunset_dt)

        if lunar_month not in ("Phalguna", "फाल्गुन"):
            current_date += timedelta(days=1)
            continue

        # 3️⃣ Ensure Purnima window actually includes sunset
        tithi_start = tithi.get("start_ist")
        tithi_end = tithi.get("end_ist")

        if not (tithi_start and tithi_end):
            current_date += timedelta(days=1)
            continue

        tithi_start_dt = datetime.strptime(tithi_start, "%Y-%m-%d %H:%M")
        tithi_end_dt = datetime.strptime(tithi_end, "%Y-%m-%d %H:%M")

        if not (tithi_start_dt <= sunset_dt <= tithi_end_dt):
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
                "tithi_at_sunset": tithi_at_sunset,
            },

            "holi_dhulandi": {
                "date": holi_date.strftime("%Y-%m-%d"),
            },

            "lunar_details": {
                "month": lunar_month,
                "paksha": tithi.get("paksha"),
                "tithi_name": tithi.get("name"),
                "tithi_start": tithi_start,
                "tithi_end": tithi_end,
            }
        }

        current_date += timedelta(days=1)

    return None
