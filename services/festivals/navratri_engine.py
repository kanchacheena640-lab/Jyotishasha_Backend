from datetime import datetime, timedelta
from services.panchang_engine import calculate_sunrise_sunset
from services.astro_core import _tithi_number_at
from services.lunar_month_engine import get_amanta_month

def detect_navratri(year, lat, lon, navratri_type="chaitra"):
    target_month = "Chaitra" if navratri_type == "chaitra" else "Ashwin"
    # Search window adjusted for March start
    d = datetime(year, 3, 1).date() if navratri_type == "chaitra" else datetime(year, 9, 1).date()
    search_end = d + timedelta(days=60)

    navratri_days = []
    started = False

    while d <= search_end:
        dt_input = datetime.combine(d, datetime.min.time())
        sunrise_dt, _ = calculate_sunrise_sunset(dt_input, lat, lon)
        lunar_info = get_amanta_month(sunrise_dt)
        tithi = _tithi_number_at(sunrise_dt)

        if not started:
            # Rule: Shuddha Month + Tithi 1
            if lunar_info["name"] == target_month and not lunar_info["is_adhik"]:
                tithi_sunrise = _tithi_number_at(sunrise_dt)  # पहले से है, rename कर सकते हो

                if tithi_sunrise == 1:
                    started = True
                
                elif tithi_sunrise == 30:
                    # +12 hours पर चेक (2026 fix + future safe)
                    if _tithi_number_at(sunrise_dt + timedelta(hours=12)) == 1:
                        started = True
                
                # Optional extra safety: अगर +12h पर miss हो (बहुत rare), +15h तक extend
                # elif _tithi_number_at(sunrise_dt + timedelta(hours=15)) == 1:
                #     started = True

                if started:
                    navratri_days.append({
                        "day_number": 1,
                        "date": str(d),
                        "tithi": 1,          # effective tithi day के लिए 1 hardcode करो
                        "label": "Kalash Sthapana"
                    })
        else:
            if 1 <= tithi <= 9:
                # Avoid duplicates on the same Tithi if it's a Vriddhi day
                if str(d) not in [x['date'] for x in navratri_days]:
                    day_num = len(navratri_days) + 1
                    navratri_days.append({"day_number": day_num, "date": str(d), "tithi": tithi, "label": f"Navratri Day {day_num}"})
            
            if tithi >= 10 or len(navratri_days) >= 10:
                break

        d += timedelta(days=1)

    if not navratri_days:
        return {"error": "Navratri dates not found for this year", "year": year}

    return {
        "type": navratri_type,
        "year": year,
        "total_days": len(navratri_days),
        "kalash_sthapana_date": navratri_days[0]["date"],
        "days": navratri_days
    }