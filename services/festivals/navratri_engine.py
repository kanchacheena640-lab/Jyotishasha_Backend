from datetime import datetime, timedelta
from services.panchang_engine import calculate_sunrise_sunset
from services.astro_core import _tithi_number_at
from services.lunar_month_engine import get_lunar_month

def detect_navratri(year, lat, lon, navratri_type="chaitra"):
    # 1. Vedic Boundary Logic
    if navratri_type == "chaitra":
        target_month = "Chaitra"
        # 18 March 2026 ko pakadne ke liye March 1 se start
        search_start = datetime(year, 3, 1).date()
    else:
        target_month = "Ashwin"
        search_start = datetime(year, 9, 1).date()

    navratri_days = []
    started = False
    d = search_start

    # Max 60 days scan for safety (Adhik Maas handling)
    for _ in range(60):
        dt_input = datetime.combine(d, datetime.min.time())
        # Sunrise ownership rule
        sunrise_dt, _ = calculate_sunrise_sunset(dt_input, lat, lon)
        
        tithi = _tithi_number_at(sunrise_dt)
        lunar_data = get_lunar_month(sunrise_dt)
        l_month = lunar_data.get("name")

        # --- START LOGIC (Kalash Sthapana) ---
        if not started:
            # Rule: Month must match and it must be Shukla Pratipada (Tithi 1 after 30)
            if l_month == target_month and tithi == 1:
                # Expert Check: Pichle sunrise par Amavasya (30) honi chahiye
                yesterday_sunrise = sunrise_dt - timedelta(days=1)
                tithi_yesterday = _tithi_number_at(yesterday_sunrise)
                
                if tithi_yesterday == 30 or tithi_yesterday == 29:
                    started = True
                    navratri_days.append({
                        "day_number": 1,
                        "date": d.strftime("%Y-%m-%d"),
                        "tithi": 1,
                        "label": "Kalash Sthapana"
                    })

        # --- CONTINUATION LOGIC ---
        elif started:
            # Navratri Day 2 to 9
            # Rule: Jab tak Sunrise par Tithi 9 khatam na ho jaye
            if 1 <= tithi <= 9:
                last_day = navratri_days[-1]
                
                # Logic to handle Tithi Vriddhi (Same tithi on two sunrises)
                # Day count will always increase to ensure 9 nights
                day_num = len(navratri_days) + 1
                
                navratri_days.append({
                    "day_number": day_num,
                    "date": d.strftime("%Y-%m-%d"),
                    "tithi": tithi,
                    "label": f"Navratri Day {day_num}"
                })
                
                if tithi == 9:
                    # Agar agle sunrise par tithi 9 nahi hai, toh aaj hi akhri din hai
                    if _tithi_number_at(sunrise_dt + timedelta(days=1)) != 9:
                        break
            else:
                # Agar sunrise par tithi 10 (Dashami) aa gayi, toh Navratri over
                break

        d += timedelta(days=1)
        if len(navratri_days) >= 10: # Safety break for max days
            break

    return {
        "type": navratri_type,
        "year": year,
        "total_days": len(navratri_days),
        "kalash_sthapana": navratri_days[0]["date"] if navratri_days else None,
        "days": navratri_days
    }