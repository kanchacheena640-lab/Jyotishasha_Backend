from datetime import datetime, timedelta
from services.panchang_engine import calculate_sunrise_sunset
from services.astro_core import _tithi_number_at
from services.lunar_month_engine import get_amanta_month

def detect_navratri(year, lat, lon, navratri_type="chaitra"):
    target_month = "Chaitra" if navratri_type == "chaitra" else "Ashwin"
    # Search window 1 month early for safety
    d = datetime(year, 2, 15).date() if navratri_type == "chaitra" else datetime(year, 8, 15).date()
    search_end = d + timedelta(days=90)

    navratri_days = []
    started = False

    while d <= search_end:
        dt_input = datetime.combine(d, datetime.min.time())
        sunrise_dt, _ = calculate_sunrise_sunset(dt_input, lat, lon)
        
        # Calling the updated Adhik-aware engine
        lunar_info = get_amanta_month(sunrise_dt)
        tithi = _tithi_number_at(sunrise_dt)

        if not started:
            # SHASTRIYA RULE: Month matches + NOT Adhik + Tithi is 1
            if lunar_info["name"] == target_month and not lunar_info.get("is_adhik", False):
                if tithi == 1:
                    started = True
                elif tithi == 30: # Case where Pratipada starts slightly after sunrise
                    for m in range(10, 600, 10):
                        if _tithi_number_at(sunrise_dt + timedelta(minutes=m)) == 1:
                            started = True
                            break
                
                if started:
                    navratri_days.append({
                        "day_number": 1,
                        "date": d.strftime("%Y-%m-%d"),
                        "tithi": tithi,
                        "label": "Kalash Sthapana"
                    })
        else:
            # PHASE 2: Counting (Handles Kshaya/Vriddhi)
            if 1 <= tithi <= 9:
                # Always increment from previous day to handle 8/10 days correctly
                day_num = len(navratri_days) + 1
                navratri_days.append({
                    "day_number": day_num,
                    "date": d.strftime("%Y-%m-%d"),
                    "tithi": tithi,
                    "label": f"Navratri Day {day_num}"
                })
            
            # EXIT CONDITIONS
            if tithi >= 10: break # Dashami at sunrise
            if tithi == 9: # Navami check
                next_sun, _ = calculate_sunrise_sunset(dt_input + timedelta(days=1), lat, lon)
                if _tithi_number_at(next_sun) >= 10: break

        d += timedelta(days=1)

    # CRITICAL FIX for 2027: Stop the IndexError
    if not navratri_days:
        return {"type": navratri_type, "year": year, "total_days": 0, "days": [], "error": "Dates not found"}

    return {
        "type": navratri_type,
        "year": year,
        "total_days": len(navratri_days),
        "kalash_sthapana_date": navratri_days[0]["date"],
        "days": navratri_days
    }