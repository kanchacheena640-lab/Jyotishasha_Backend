from datetime import datetime, timedelta
from services.panchang_engine import (
    calculate_panchang,
    _tithi_number_at,
    _karan_at
)
from services.lunar_month_engine import get_lunar_month


def _get_bhadra_end_time(start_time, max_hours=18):
    """
    Returns exact datetime when Vishti Karana (Bhadra) ends.
    """
    check_time = start_time
    limit_time = start_time + timedelta(hours=max_hours)

    while check_time <= limit_time:
        k_name, _ = _karan_at(check_time)
        if k_name != "Vishti (Bhadra)":
            return check_time
        check_time += timedelta(minutes=1)

    return None


def detect_holi(year, lat, lon, language="en"):

    start_date = datetime(year, 2, 15).date()
    end_date = datetime(year, 4, 15).date()

    d = start_date

    while d <= end_date:

        p = calculate_panchang(d, lat, lon, language)
        sunset_str = p.get("sunset")
        weekday = p.get("weekday")

        if not sunset_str:
            d += timedelta(days=1)
            continue

        sunset_dt = datetime.strptime(
            f"{d} {sunset_str}",
            "%Y-%m-%d %H:%M"
        )

        # 🔥 RULE 1: Purnima must exist at Sunset
        if _tithi_number_at(sunset_dt) != 15:
            d += timedelta(days=1)
            continue

        # 🔥 RULE 2: Lunar month must be Phalguna
        lunar_month = get_lunar_month(sunset_dt)
        if lunar_month not in ("Phalguna", "फाल्गुन"):
            d += timedelta(days=1)
            continue

        # 🔥 RULE 3: Bhadra handling
        karan_name, _ = _karan_at(sunset_dt)

        # Case A: No Bhadra → Same day Holika
        if karan_name != "Vishti (Bhadra)":
            dahan_date = d
            final_weekday = weekday
            final_sunset = sunset_str
            final_karan = karan_name

        else:
            # Bhadra active at Sunset
            next_day = d + timedelta(days=1)

            p_next = calculate_panchang(next_day, lat, lon, language)
            sunset_next = p_next.get("sunset")
            weekday_next = p_next.get("weekday")

            if not sunset_next:
                d += timedelta(days=1)
                continue

            sunset_next_dt = datetime.strptime(
                f"{next_day} {sunset_next}",
                "%Y-%m-%d %H:%M"
            )

            # 🔥 Check if Purnima still at next Sunset
            if _tithi_number_at(sunset_next_dt) == 15:

                # Check Bhadra next day
                k_next, _ = _karan_at(sunset_next_dt)

                if k_next != "Vishti (Bhadra)":
                    # Shift to next day
                    dahan_date = next_day
                    final_weekday = weekday_next
                    final_sunset = sunset_next
                    final_karan = k_next
                else:
                    # Rare double Bhadra case
                    d += timedelta(days=1)
                    continue

            else:
                # 🔥 Purnima ends before next sunset
                # Must do same day after Bhadra ends

                bhadra_end = _get_bhadra_end_time(sunset_dt)

                if bhadra_end and _tithi_number_at(bhadra_end) == 15:
                    dahan_date = d
                    final_weekday = weekday
                    final_sunset = bhadra_end.strftime("%H:%M")
                    final_karan = "Post-Bhadra"
                else:
                    d += timedelta(days=1)
                    continue

        # ✅ FINAL RETURN
        return {
            "year": year,
            "holika_dahan": {
                "date": dahan_date.strftime("%Y-%m-%d"),
                "weekday": final_weekday,
                "muhurta_start": final_sunset,
                "karan_status": final_karan,
            },
            "holi_dhulandi": {
                "date": (dahan_date + timedelta(days=1)).strftime("%Y-%m-%d"),
            },
            "lunar_details": {
                "month": lunar_month,
            },
        }

    return None
