# services/festivals/holi_engine.py

from datetime import datetime, timedelta
from services.panchang_engine import (
    calculate_panchang,
    _tithi_number_at
)


def detect_holi(year, lat, lon, language="en"):
    """
    Detect Holi for given year.
    Based on:
    - Phalguna Shukla Purnima (Holika Dahan)
    - Next day = Dhulandi / Rangwali Holi
    Uses Amanta month system.
    """

    start_date = datetime(year, 1, 1).date()
    end_date = datetime(year, 12, 31).date()

    current_date = start_date

    while current_date <= end_date:

        panchang = calculate_panchang(
            current_date, lat, lon, language
        )

        tithi = panchang.get("tithi", {})
        month_name = panchang.get("month_name")
        sunset_str = panchang.get("sunset")

        if not (tithi and sunset_str):
            current_date += timedelta(days=1)
            continue

        # 🔥 Purnima check at SUNSET (not noon)
        sunset_dt = datetime.strptime(
            f"{current_date} {sunset_str}",
            "%Y-%m-%d %H:%M"
        )

        tithi_at_sunset = _tithi_number_at(sunset_dt)

        if (
            tithi_at_sunset == 15
            and month_name in ("Phalguna", "फाल्गुन")
        ):

            # Holika Dahan = same evening
            holika_dahan_date = current_date

            # Dhulandi = next day
            holi_date = current_date + timedelta(days=1)

            return {
                "year": year,

                "holika_dahan": {
                    "date": holika_dahan_date.strftime("%Y-%m-%d"),
                    "weekday": panchang.get("weekday"),
                    "sunset_time": sunset_str,
                    "tithi_at_sunset": 15,
                },

                "holi_dhulandi": {
                    "date": holi_date.strftime("%Y-%m-%d"),
                },

                "lunar_details": {
                    "month": month_name,
                    "paksha": tithi.get("paksha"),
                    "tithi_name": tithi.get("name"),
                    "tithi_start": tithi.get("start_ist"),
                    "tithi_end": tithi.get("end_ist"),
                }
            }

        current_date += timedelta(days=1)

    return None
