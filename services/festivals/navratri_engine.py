from datetime import datetime, timedelta
from services.panchang_engine import calculate_sunrise_sunset
from services.astro_core import _tithi_number_at


def detect_navratri(year, lat, lon, navratri_type="chaitra"):
    if navratri_type == "chaitra":
        d = datetime(year, 3, 1).date()
        search_end = datetime(year, 4, 25).date()
    else:
        d = datetime(year, 9, 1).date()
        search_end = datetime(year, 10, 30).date()

    navratri_days = []
    started = False
    
    # Loop ko limited rakhte hain (Security limit: 60 days max)
    iterations = 0
    while d <= search_end and iterations < 60:
        iterations += 1
        dt_input = datetime.combine(d, datetime.min.time())
        
        # Heavy calculations
        sunrise_dt, _ = calculate_sunrise_sunset(dt_input, lat, lon)
        tithi = _tithi_number_at(sunrise_dt)

        if not started:
            # Day 1 Search
            if tithi == 1:
                yesterday_sunrise = sunrise_dt - timedelta(days=1)
                tithi_yesterday = _tithi_number_at(yesterday_sunrise)
                
                # Check for Amavasya phase to confirm Shukla Paksha
                if tithi_yesterday in [28, 29, 30]:
                    started = True
                    navratri_days.append({
                        "day_number": 1,
                        "date": d.strftime("%Y-%m-%d"),
                        "tithi": 1,
                        "label": "Kalash Sthapana"
                    })
        else:
            # Day 2 to 9
            if 1 <= tithi <= 9:
                current_day_count = len(navratri_days) + 1
                navratri_days.append({
                    "day_number": current_day_count,
                    "date": d.strftime("%Y-%m-%d"),
                    "tithi": tithi,
                    "label": f"Navratri Day {current_day_count}"
                })
                
                # Day 9 completion logic
                if tithi == 9:
                    next_day_sunrise = sunrise_dt + timedelta(days=1)
                    if _tithi_number_at(next_day_sunrise) != 9:
                        # 🔥 CRITICAL: Sab mil gaya, loop se bahar niklo turant!
                        return format_nav_output(navratri_type, year, navratri_days)
            else:
                # Agar Dashami aa gayi toh bhi exit
                break

        d += timedelta(days=1)

    return format_nav_output(navratri_type, year, navratri_days)

def format_nav_output(nav_type, year, days_list):
    """Helper to ensure clean exit and formatting"""
    return {
        "type": nav_type,
        "year": year,
        "total_days": len(days_list),
        "kalash_sthapana_date": days_list[0]["date"] if days_list else None,
        "days": days_list
    }