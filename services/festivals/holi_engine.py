from datetime import datetime, timedelta
from services.panchang_engine import calculate_panchang, _tithi_number_at
from services.lunar_month_engine import get_lunar_month


def detect_holi(year, lat, lon, language="en"):
    """
    Detect Holi for given year.
    Rule:
    - Phalguna Shukla Purnima at SUNSET = Holika Dahan
    - Next day = Dhulandi
    Uses Amanta lunar system.
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

        # Create sunset datetime
        sunset_dt = datetime.strptime(
            f"{current_date} {sunset_str}",
            "%Y-%m-%d %H:%M"
        )

        # 1️⃣ Check Tithi at sunset
        tithi_at_sunset = _tithi_number_at(sunset_dt)

        if tithi_at_sunset != 15:
            current_date += timedelta(days=1)
            continue

        # 2️⃣ Get lunar month at sunset moment (SAFE way)
        lunar_month = get_lunar_month(sunset_dt)

        if lunar_month not in ("Phalguna", "फाल्गुन"):
            current_date += timedelta(days=1)
            continue

        # 3️⃣ Valid Holika Dahan found
        holika_dahan_date = current_date
        holi_date = current_date + timedelta(days=1)

        # Recalculate panchang for proper tithi details
        tithi = panchang.get("tithi", {})

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
            },

            "lunar_details": {
                "month": lunar_month,
                "paksha": tithi.get("paksha"),
                "tithi_name": tithi.get("name"),
                "tithi_start": tithi.get("start_ist"),
                "tithi_end": tithi.get("end_ist"),
            }
        }

    return None
