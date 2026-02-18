# services/festivals/holi_engine.py

from datetime import datetime, timedelta
from services.panchang_engine import calculate_panchang, _tithi_number_at, _karan_at
from services.lunar_month_engine import get_lunar_month


def detect_holi(year, lat, lon, language="en"):
    """
    Industry-standard rule (matching Drik-style behavior):
    - Find day where Purnima tithi is present in Pradosh (sunset+~2h)
    - Lunar month at that Pradosh moment must be Phalguna (Amanta)
    - Bhadra (Vishti) must NOT be active in that Pradosh moment
    - That evening = Holika Dahan
    - Next day = Dhulandi
    """

    start_date = datetime(year, 2, 15).date()
    end_date = datetime(year, 4, 15).date()
    d = start_date

    while d <= end_date:
        p = calculate_panchang(d, lat, lon, language)
        sunset_str = p.get("sunset")
        if not sunset_str:
            d += timedelta(days=1)
            continue

        # Use a stable Pradosh-check moment (sunset + 60 minutes)
        sunset_dt = datetime.strptime(f"{d} {sunset_str}", "%Y-%m-%d %H:%M")
        pradosh_dt = sunset_dt + timedelta(minutes=60)

        # 1) Tithi must be Purnima at Pradosh
        tithi_at_pradosh = _tithi_number_at(pradosh_dt)
        if tithi_at_pradosh != 15:
            d += timedelta(days=1)
            continue

        # 🔍 DEBUG PRINT ADD HERE
        lunar_month = get_lunar_month(pradosh_dt)
        karan_name, _ = _karan_at(pradosh_dt)

        print(
            d,
            "Tithi:", tithi_at_pradosh,
            "Month:", lunar_month,
            "Karan:", karan_name
        )

        # 2) Lunar month check
        if lunar_month not in ("Phalguna", "फाल्गुन"):
            d += timedelta(days=1)
            continue

        # 3) Bhadra avoidance (Vishti karan) at Pradosh moment
        karan_name, _ = _karan_at(pradosh_dt)
        if karan_name == "Vishti (Bhadra)":
            d += timedelta(days=1)
            continue

        # ✅ Found Holika Dahan day
        return {
            "year": year,
            "holika_dahan": {
                "date": d.strftime("%Y-%m-%d"),
                "weekday": p.get("weekday"),
                "sunset_time": sunset_str,
                "tithi_at_pradosh": 15,
                "karan_at_pradosh": karan_name,
            },
            "holi_dhulandi": {
                "date": (d + timedelta(days=1)).strftime("%Y-%m-%d"),
            },
            "lunar_details": {
                "month": lunar_month,
            },
        }

    return None

