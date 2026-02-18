from datetime import datetime, timedelta
from services.panchang_engine import calculate_panchang, _tithi_number_at, _karan_at
from services.lunar_month_engine import get_lunar_month


def _is_valid_holika_day(date_obj, lat, lon, language):
    """
    Returns tuple:
    (is_valid, lunar_month, karan_name, weekday, sunset_time)
    """

    p = calculate_panchang(date_obj, lat, lon, language)
    sunset_str = p.get("sunset")
    weekday = p.get("weekday")

    if not sunset_str:
        return False, None, None, None, None

    sunset_dt = datetime.strptime(
        f"{date_obj} {sunset_str}",
        "%Y-%m-%d %H:%M"
    )

    # 🔥 Full Pradosh window (sunset → +2h)
    pradosh_start = sunset_dt
    pradosh_end = sunset_dt + timedelta(hours=2)

    check_time = pradosh_start
    pradosh_match_time = None

    # Check Purnima anywhere in Pradosh
    while check_time <= pradosh_end:
        if _tithi_number_at(check_time) == 15:
            pradosh_match_time = check_time
            break
        check_time += timedelta(minutes=5)

    if not pradosh_match_time:
        return False, None, None, None, None

    lunar_month = get_lunar_month(pradosh_match_time)

    if lunar_month not in ("Phalguna", "फाल्गुन"):
        return False, None, None, None, None

    karan_name, _ = _karan_at(pradosh_match_time)

    if karan_name == "Vishti (Bhadra)":

        # 🔍 Check if Bhadra ends inside Pradosh window
        check_time = pradosh_match_time
        bhadra_end_time = None

        while check_time <= pradosh_end:
            k_name, _ = _karan_at(check_time)
            if k_name != "Vishti (Bhadra)":
                bhadra_end_time = check_time
                break
            check_time += timedelta(minutes=5)

        # Case 1: Bhadra ends inside Pradosh → same day allowed
        if bhadra_end_time:
            pradosh_match_time = bhadra_end_time
            karan_name, _ = _karan_at(bhadra_end_time)

        else:
            # Case 2: Bhadra continues full Pradosh → shift to next day
            next_day = d + timedelta(days=1)
            next_p = calculate_panchang(next_day, lat, lon, language)
            next_sunset = next_p.get("sunset")

            if not next_sunset:
                return False, lunar_month, karan_name, weekday, sunset_str

            next_sunset_dt = datetime.strptime(
                f"{next_day} {next_sunset}",
                "%Y-%m-%d %H:%M"
            )

            # find first non-Bhadra time
            check_time = next_sunset_dt
            valid_time = None

            while check_time <= next_sunset_dt + timedelta(hours=2):
                k_name, _ = _karan_at(check_time)
                if k_name != "Vishti (Bhadra)":
                    valid_time = check_time
                    break
                check_time += timedelta(minutes=5)

            if not valid_time:
                return False, lunar_month, karan_name, weekday, sunset_str

            # shift Dahan
            d = next_day
            sunset_str = next_sunset
            karan_name, _ = _karan_at(valid_time)

    return True, lunar_month, karan_name, weekday, sunset_str



def detect_holi(year, lat, lon, language="en"):
    """
    Final Holi logic (Primary + Fallback)

    1️⃣ Find Phalguna Purnima in Pradosh.
    2️⃣ If Bhadra not active → Holika Dahan.
    3️⃣ If Bhadra active → Check next day:
          If Purnima still in Pradosh AND Bhadra gone → Next day.
    """

    start_date = datetime(year, 2, 15).date()
    end_date = datetime(year, 4, 15).date()

    d = start_date

    while d <= end_date:

        valid, lunar_month, karan, weekday, sunset = \
            _is_valid_holika_day(d, lat, lon, language)

        # ✅ Primary condition
        if valid:
            return {
                "year": year,
                "holika_dahan": {
                    "date": d.strftime("%Y-%m-%d"),
                    "weekday": weekday,
                    "sunset_time": sunset,
                    "karan_at_pradosh": karan,
                },
                "holi_dhulandi": {
                    "date": (d + timedelta(days=1)).strftime("%Y-%m-%d"),
                },
                "lunar_details": {
                    "month": lunar_month,
                },
            }

        # 🔁 Fallback check (if Purnima but Bhadra issue)
        # Check next day only if same lunar month window
        next_day = d + timedelta(days=1)

        valid_next, lunar_month_next, karan_next, weekday_next, sunset_next = \
            _is_valid_holika_day(next_day, lat, lon, language)

        if valid_next:
            return {
                "year": year,
                "holika_dahan": {
                    "date": next_day.strftime("%Y-%m-%d"),
                    "weekday": weekday_next,
                    "sunset_time": sunset_next,
                    "karan_at_pradosh": karan_next,
                },
                "holi_dhulandi": {
                    "date": (next_day + timedelta(days=1)).strftime("%Y-%m-%d"),
                },
                "lunar_details": {
                    "month": lunar_month_next,
                },
            }

        d += timedelta(days=1)

    return None
