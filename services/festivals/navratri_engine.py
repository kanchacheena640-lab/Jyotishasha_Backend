from datetime import datetime, timedelta
from services.panchang_engine import calculate_sunrise_sunset
from services.astro_core import _tithi_number_at
from services.lunar_month_engine import get_lunar_month


def detect_navratri(year, lat, lon, navratri_type="chaitra"):

    if navratri_type == "chaitra":
        target_month = "Chaitra"
        start_range = datetime(year, 3, 1).date()
        end_range = datetime(year, 4, 30).date()
    else:
        target_month = "Ashwin"
        start_range = datetime(year, 9, 1).date()
        end_range = datetime(year, 10, 31).date()

    navratri_days = []
    started = False
    previous_tithi = None

    d = start_range

    while d <= end_range:

        dt_input = datetime.combine(d, datetime.min.time())
        sunrise_dt, _ = calculate_sunrise_sunset(dt_input, lat, lon)

        lunar_data = get_lunar_month(sunrise_dt)
        lunar_month = lunar_data["name"]
        tithi = _tithi_number_at(sunrise_dt)

        # -------- START DETECTION --------
        if not started:
            if lunar_month == target_month and tithi == 1:
                started = True
                navratri_days.append({
                    "day_number": 1,
                    "date": d.strftime("%Y-%m-%d"),
                    "tithi": 1,
                    "label": "Kalash Sthapana"
                })
                previous_tithi = 1

        # -------- CONTINUE NAVRATRI --------
        else:
            if lunar_month == target_month and 1 <= tithi <= 9:

                if tithi == previous_tithi:
                    # Vriddhi case (same tithi repeat)
                    day_number = navratri_days[-1]["day_number"] + 1
                else:
                    day_number = tithi

                navratri_days.append({
                    "day_number": day_number,
                    "date": d.strftime("%Y-%m-%d"),
                    "tithi": tithi,
                    "label": f"Navratri Day {day_number}"
                })

                previous_tithi = tithi

                if tithi == 9:
                    break
            else:
                # Month changed or tithi out of range
                break

        d += timedelta(days=1)

    return {
        "type": navratri_type,
        "year": year,
        "total_days": len(navratri_days),
        "kalash_sthapana_date": navratri_days[0]["date"] if navratri_days else None,
        "days": navratri_days
    }