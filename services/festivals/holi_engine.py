from datetime import datetime, timedelta
from services.panchang_engine import calculate_panchang, _tithi_number_at, _karan_at
from services.lunar_month_engine import get_lunar_month


def _is_valid_holika_day(date_obj, lat, lon, language):
    """
    Returns tuple:
    (is_valid, lunar_month, karan_name, weekday, sunset_time)

    Rules:
    - Purnima must occur during Pradosh (sunset → +2h)
    - Lunar month must be Phalguna
    - If Bhadra active at Purnima moment:
          • If Bhadra ends within Pradosh → allowed
          • If Bhadra continues full Pradosh → reject
    """

    p = calculate_panchang(date_obj, lat, lon, language)
    sunset_str = p.get("sunset")
    weekday = p.get("weekday")

    if not sunset_str:
        return "invalid", None, None, None, None

    sunset_dt = datetime.strptime(
        f"{date_obj} {sunset_str}",
        "%Y-%m-%d %H:%M"
    )

    # Pradosh window
    pradosh_start = sunset_dt
    pradosh_end = sunset_dt + timedelta(hours=2)

    # 🔍 Find Purnima inside Pradosh
    check_time = pradosh_start
    pradosh_match_time = None

    while check_time <= pradosh_end:
        if _tithi_number_at(check_time) == 15:
            pradosh_match_time = check_time
            break
        check_time += timedelta(minutes=5)

    if not pradosh_match_time:
        return "invalid", None, None, None, None

    # 🌙 Lunar month check
    lunar_month = get_lunar_month(pradosh_match_time)

    if lunar_month not in ("Phalguna", "फाल्गुन"):
        return "invalid", None, None, None, None

    # 🔥 Karan check
    karan_name, _ = _karan_at(pradosh_match_time)

    if karan_name == "Vishti (Bhadra)":

        # Check if Bhadra ends within Pradosh window
        check_time = pradosh_match_time
        bhadra_end_time = None

        while check_time <= pradosh_end:
            k_name, _ = _karan_at(check_time)
            if k_name != "Vishti (Bhadra)":
                bhadra_end_time = check_time
                break
            check_time += timedelta(minutes=5)

        # If Bhadra continues full Pradosh → reject
        if not bhadra_end_time:
            return "bhadra_full_pradosh", lunar_month, karan_name, weekday, sunset_str


        # If Bhadra ends inside Pradosh → valid at that moment
        karan_name, _ = _karan_at(bhadra_end_time)

    # ✅ Valid Holika Dahan Day
    return "valid", lunar_month, karan_name, weekday, sunset_str


def detect_holi(year, lat, lon, language="en"):

    start_date = datetime(year, 2, 15).date()
    end_date = datetime(year, 4, 15).date()

    d = start_date

    while d <= end_date:

        status, lunar_month, karan, weekday, sunset = \
            _is_valid_holika_day(d, lat, lon, language)

        # ✅ Valid same day
        if status == "valid":
            dahan_date = d

        # 🔥 Bhadra full Pradosh → shift next day
        elif status == "bhadra_full_pradosh":

            # 🔒 Safety: confirm Purnima really at this day's Pradosh start
            p_current = calculate_panchang(d, lat, lon, language)
            sunset_current = p_current.get("sunset")

            if not sunset_current:
                d += timedelta(days=1)
                continue

            sunset_dt_current = datetime.strptime(
                f"{d} {sunset_current}",
                "%Y-%m-%d %H:%M"
            )

            pradosh_start = sunset_dt_current

            if _tithi_number_at(pradosh_start) != 15:
                d += timedelta(days=1)
                continue

            next_day = d + timedelta(days=1)

            # Only check Bhadra in next day's Pradosh
            p_next = calculate_panchang(next_day, lat, lon, language)
            sunset_next = p_next.get("sunset")
            weekday_next = p_next.get("weekday")

            if not sunset_next:
                d += timedelta(days=1)
                continue

            sunset_dt_next = datetime.strptime(
                f"{next_day} {sunset_next}",
                "%Y-%m-%d %H:%M"
            )

            pradosh_start = sunset_dt_next
            pradosh_end = sunset_dt_next + timedelta(hours=2)

            check_time = pradosh_start
            bhadra_active = True

            while check_time <= pradosh_end:
                k_name, _ = _karan_at(check_time)
                if k_name != "Vishti (Bhadra)":
                    bhadra_active = False
                    karan = k_name
                    break
                check_time += timedelta(minutes=5)

            if bhadra_active:
                d += timedelta(days=1)
                continue

            dahan_date = next_day
            weekday = weekday_next
            sunset = sunset_next

        else:
            d += timedelta(days=1)
            continue

        return {
            "year": year,
            "holika_dahan": {
                "date": dahan_date.strftime("%Y-%m-%d"),
                "weekday": weekday,
                "sunset_time": sunset,
                "karan_at_pradosh": karan,
            },
            "holi_dhulandi": {
                "date": (dahan_date + timedelta(days=1)).strftime("%Y-%m-%d"),
            },
            "lunar_details": {
                "month": lunar_month,
            },
        }

    return None
