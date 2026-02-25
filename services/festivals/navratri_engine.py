from datetime import datetime, timedelta
from services.panchang_engine import calculate_sunrise_sunset
from services.astro_core import _tithi_number_at


def detect_navratri(year, lat, lon, navratri_type="chaitra"):

    if navratri_type == "chaitra":
        search_start = datetime(year, 3, 1).date()
        search_end = datetime(year, 4, 25).date()
    else:
        search_start = datetime(year, 9, 1).date()
        search_end = datetime(year, 10, 30).date()

    navratri_days = []
    started = False
    previous_tithi = None

    d = search_start

    while d <= search_end:

        dt_input = datetime.combine(d, datetime.min.time())
        sunrise_dt, _ = calculate_sunrise_sunset(dt_input, lat, lon)
        tithi = _tithi_number_at(sunrise_dt)

        # ---- START CONDITION ----
        if not started:

            if tithi == 1:

                prev_date = d - timedelta(days=1)
                prev_dt = datetime.combine(prev_date, datetime.min.time())
                prev_sunrise, _ = calculate_sunrise_sunset(prev_dt, lat, lon)
                prev_tithi = _tithi_number_at(prev_sunrise)

                if prev_tithi in (29, 30):
                    started = True
                    navratri_days.append({
                        "day_number": 1,
                        "date": d.strftime("%Y-%m-%d"),
                        "tithi": 1,
                        "label": "Kalash Sthapana"
                    })
                    previous_tithi = 1

        else:

            if 1 <= tithi <= 9:

                if tithi == previous_tithi:
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
                break

        d += timedelta(days=1)

    return {
        "type": navratri_type,
        "year": year,
        "total_days": len(navratri_days),
        "kalash_sthapana_date": navratri_days[0]["date"] if navratri_days else None,
        "days": navratri_days
    }