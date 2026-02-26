from datetime import datetime, timedelta
from services.panchang_engine import calculate_sunrise_sunset
from services.astro_core import _tithi_number_at
from services.lunar_month_engine import get_amanta_month

def detect_navratri(year, lat, lon, navratri_type="chaitra"):

    print(f"\n===== NAVRATRI DEBUG START | YEAR={year} | TYPE={navratri_type} =====")

    target_month_name = "Chaitra" if navratri_type == "chaitra" else "Ashwin"

    start_date = datetime(year, 3, 1).date() if navratri_type == "chaitra" else datetime(year, 9, 1).date()
    d = start_date
    search_end = d + timedelta(days=80)

    navratri_days = []
    started = False

    while d <= search_end:

        print("\n--------------------------------------------------")

        dt_input = datetime.combine(d, datetime.min.time())
        sunrise_dt, _ = calculate_sunrise_sunset(dt_input, lat, lon)

        tithi_sunrise = _tithi_number_at(sunrise_dt)
        tithi_6h = _tithi_number_at(sunrise_dt + timedelta(hours=6))
        tithi_12h = _tithi_number_at(sunrise_dt + timedelta(hours=12))

        lunar_info = get_amanta_month(sunrise_dt)

        print(f"DATE: {d}")
        print(f"  Sunrise: {sunrise_dt}")
        print(f"  Tithi@Sunrise: {tithi_sunrise}")
        print(f"  Tithi+6h: {tithi_6h}")
        print(f"  Tithi+12h: {tithi_12h}")
        print(f"  Month: {lunar_info['name']}")
        print(f"  Adhik: {lunar_info['is_adhik']}")

        # -------- PREVIOUS DAY DEBUG --------
        prev_date = d - timedelta(days=1)
        prev_sunrise, _ = calculate_sunrise_sunset(
            datetime.combine(prev_date, datetime.min.time()),
            lat, lon
        )

        prev_tithi = _tithi_number_at(prev_sunrise)
        prev_month = get_amanta_month(prev_sunrise)["name"]

        print(f"  Prev Date: {prev_date}")
        print(f"  Prev Tithi@Sunrise: {prev_tithi}")
        print(f"  Prev Month: {prev_month}")

        # -------- START CONDITION CHECK --------
        pratipada_present = (
            tithi_sunrise == 1
            or tithi_6h == 1
            or tithi_12h == 1
        )

        print(f"  Pratipada Present In Day Window: {pratipada_present}")
        print(f"  Month Match: {lunar_info['name'] == target_month_name}")
        print(f"  Prev Month Different: {prev_month != target_month_name}")

        if not started:

            # -------- NORMAL RULE --------
            # Sunrise पर Pratipada मिले
            if (
                lunar_info["name"] == target_month_name
                and tithi_sunrise == 1
            ):
                print("  >>> NORMAL NAVRATRI START DETECTED")
                started = True

                navratri_days.append({
                    "day_number": 1,
                    "date": d.strftime("%Y-%m-%d"),
                    "tithi": 1,
                    "label": "Kalash Sthapana"
                })

            # -------- RARE EDGE CASE (Like 2026) --------
            else:

                # Check if TODAY sunrise = 30 (Amavasya end)
                if tithi_sunrise == 30:

                    # Check if during today Pratipada occurred
                    tithi_6h = _tithi_number_at(sunrise_dt + timedelta(hours=6))
                    tithi_12h = _tithi_number_at(sunrise_dt + timedelta(hours=12))

                    pratipada_inside_day = (
                        tithi_6h == 1 or tithi_12h == 1
                    )

                    # Check next day sunrise
                    next_date = d + timedelta(days=1)
                    next_sunrise, _ = calculate_sunrise_sunset(
                        datetime.combine(next_date, datetime.min.time()),
                        lat, lon
                    )

                    next_tithi = _tithi_number_at(next_sunrise)
                    next_month = get_amanta_month(next_sunrise)["name"]

                    if (
                        pratipada_inside_day
                        and next_tithi == 2
                        and next_month == target_month_name
                    ):
                        print("  >>> EDGE CASE NAVRATRI START DETECTED (Pratipada between sunrises)")

                        started = True

                        navratri_days.append({
                            "day_number": 1,
                            "date": d.strftime("%Y-%m-%d"),
                            "tithi": 1,
                            "label": "Kalash Sthapana"
                        })

        else:
            if 1 <= tithi_sunrise <= 10:

                if str(d) not in [x['date'] for x in navratri_days]:
                    day_num = len(navratri_days) + 1

                    print(f"  >>> Adding Day {day_num}")

                    navratri_days.append({
                        "day_number": day_num,
                        "date": d.strftime("%Y-%m-%d"),
                        "tithi": tithi_sunrise,
                        "label": f"Navratri Day {day_num}"
                    })

            if len(navratri_days) >= 9 or tithi_sunrise >= 10:
                print("  >>> STOP CONDITION TRIGGERED")
                break

        d += timedelta(days=1)

    print("\n===== NAVRATRI DEBUG END =====")

    if not navratri_days:
        return {"error": f"{navratri_type} Navratri not found for {year}", "year": year}

    return {
        "type": navratri_type,
        "year": year,
        "total_days": len(navratri_days),
        "kalash_sthapana_date": navratri_days[0]["date"],
        "days": navratri_days
    }