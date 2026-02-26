from datetime import datetime, timedelta
from services.panchang_engine import calculate_sunrise_sunset
from services.astro_core import _tithi_number_at
from services.lunar_month_engine import get_amanta_month

def detect_navratri(year, lat, lon, navratri_type="chaitra"):
    target_month_name = "Chaitra" if navratri_type == "chaitra" else "Ashwin"
    
    start_date = datetime(year, 3, 1).date() if navratri_type == "chaitra" else datetime(year, 9, 1).date()
    d = start_date
    search_end = d + timedelta(days=80)  # बढ़ाया buffer rare late cases के लिए

    navratri_days = []
    started = False

    while d <= search_end:
        dt_input = datetime.combine(d, datetime.min.time())
        sunrise_dt, _ = calculate_sunrise_sunset(dt_input, lat, lon)
        
        tithi = _tithi_number_at(sunrise_dt)
        lunar_info = get_amanta_month(sunrise_dt)

        if not started:

            prev_date = d - timedelta(days=1)
            prev_sunrise, _ = calculate_sunrise_sunset(
                datetime.combine(prev_date, datetime.min.time()),
                lat, lon
            )

            prev_month = get_amanta_month(prev_sunrise)["name"]

            # 🌙 Check tithi in full day window
            tithi_sunrise = _tithi_number_at(sunrise_dt)
            tithi_midday = _tithi_number_at(sunrise_dt + timedelta(hours=6))
            tithi_evening = _tithi_number_at(sunrise_dt + timedelta(hours=12))

            pratipada_present = (
                tithi_sunrise == 1
                or tithi_midday == 1
                or tithi_evening == 1
            )

            # 🔥 Final start rule
            if (
                lunar_info["name"] == target_month_name
                and prev_month != target_month_name
                and pratipada_present
            ):
                started = True
                navratri_days.append({
                    "day_number": 1,
                    "date": d.strftime("%Y-%m-%d"),
                    "tithi": 1,
                    "label": "Kalash Sthapana"
                })
        else:
            if 1 <= tithi <= 10:
                if str(d) not in [x['date'] for x in navratri_days]:
                    day_num = len(navratri_days) + 1
                    navratri_days.append({
                        "day_number": day_num, 
                        "date": d.strftime("%Y-%m-%d"), 
                        "tithi": tithi, 
                        "label": f"Navratri Day {day_num}"
                    })
            
            # बेहतर stop: 9 days collect होने पर या tithi 10 पर
            if len(navratri_days) >= 9 or tithi >= 10:
                break

        d += timedelta(days=1)
    
    if not navratri_days:
        return {"error": f"{navratri_type} Navratri not found for {year}", "year": year}

    return {
        "type": navratri_type,
        "year": year,
        "total_days": len(navratri_days),
        "kalash_sthapana_date": navratri_days[0]["date"],
        "days": navratri_days
    }