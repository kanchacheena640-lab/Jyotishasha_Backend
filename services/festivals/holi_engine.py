# services/festivals/holi_engine.py

from datetime import datetime, timedelta
from services.panchang_engine import calculate_panchang, _tithi_number_at, _karan_at
from services.lunar_month_engine import get_lunar_month


def detect_holi(year, lat, lon, language="en"):

    start_date = datetime(year, 2, 15).date()
    end_date = datetime(year, 4, 15).date()
    d = start_date

    while d <= end_date:

        p = calculate_panchang(d, lat, lon, language)
        sunset_str = p.get("sunset")

        if not sunset_str:
            d += timedelta(days=1)
            continue

        sunset_dt = datetime.strptime(f"{d} {sunset_str}", "%Y-%m-%d %H:%M")

        # 🔥 Full Pradosh Window
        pradosh_start = sunset_dt
        pradosh_end = sunset_dt + timedelta(hours=2)

        check_time = pradosh_start
        pradosh_match_time = None

        while check_time <= pradosh_end:
            if _tithi_number_at(check_time) == 15:
                pradosh_match_time = check_time
                break
            check_time += timedelta(minutes=5)
        print(
            "Checking:", d,
            "Purnima found:", bool(pradosh_match_time),
            "Month:", get_lunar_month(pradosh_match_time) if pradosh_match_time else None,
            "Karan:", _karan_at(pradosh_match_time)[0] if pradosh_match_time else None
        )
        if not pradosh_match_time:
            d += timedelta(days=1)
            continue

        # ✅ Lunar month at exact valid moment
        lunar_month = get_lunar_month(pradosh_match_time)

        if lunar_month not in ("Phalguna", "फाल्गुन"):
            d += timedelta(days=1)
            continue

        # Bhadra should NOT be active at Holika time
        # If Bhadra present at start of pradosh, check if it ends within pradosh window

        bhadra_present = False
        check_time = pradosh_start

        while check_time <= pradosh_end:
            karan_name, _ = _karan_at(check_time)
            if karan_name != "Vishti (Bhadra)":
                bhadra_present = False
                break
            bhadra_present = True
            check_time += timedelta(minutes=10)

        if bhadra_present:
            d += timedelta(days=1)
            continue

        # ✅ Final Holika Dahan Found
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

