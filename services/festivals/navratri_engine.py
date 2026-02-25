from datetime import datetime, timedelta
from services.panchang_engine import calculate_sunrise_sunset
from services.astro_core import _tithi_number_at
from services.lunar_month_engine import get_amanta_month

def detect_navratri(year, lat, lon, navratri_type="chaitra"):
    if navratri_type == "chaitra":
        target_month = "Chaitra"
        # Window thoda pehle se start karte hain taaki koi edge miss na ho
        search_start = datetime(year, 2, 15).date() 
        search_end = datetime(year, 4, 30).date()
    else:
        target_month = "Ashwin"
        search_start = datetime(year, 8, 15).date()
        search_end = datetime(year, 10, 31).date()

    navratri_days = []
    started = False
    d = search_start

    print(f"\n--- DEBUG START: {navratri_type.upper()} {year} ---")

    while d <= search_end:
        dt_input = datetime.combine(d, datetime.min.time())
        sunrise_dt, _ = calculate_sunrise_sunset(dt_input, lat, lon)

        # 1. Lunar Month Data
        lunar_info = get_amanta_month(sunrise_dt)
        month_name = lunar_info["name"]
        is_adhik = lunar_info.get("is_adhik", False)
        tithi = _tithi_number_at(sunrise_dt)

        # Debugging every day
        if month_name == target_month or d.day == 1: # Print only relevant or start of month
             print(f"DATE: {d} | Month: {month_name} | Adhik: {is_adhik} | Tithi: {tithi} | Started: {started}")

        # -------- START CONDITION --------
        if not started:
            # 2026 Fix: month == target AND NOT is_adhik
            if month_name == target_month and not is_adhik:
                # Case 1: Sunrise par Pratipada
                if tithi == 1:
                    print(f">>> MATCH: Starting Navratri on {d} (Sunrise Tithi 1)")
                    started = True
                # Case 2: Sunrise par 30 hai par Pratipada din mein shuru ho rahi hai
                elif tithi == 30:
                    for mins in range(10, 720, 10): 
                        if _tithi_number_at(sunrise_dt + timedelta(minutes=mins)) == 1:
                            print(f">>> MATCH: Starting Navratri on {d} (Pratipada started after sunrise)")
                            started = True
                            break
                
                if started:
                    navratri_days.append({
                        "day_number": 1,
                        "date": d.strftime("%Y-%m-%d"),
                        "tithi": tithi,
                        "label": "Kalash Sthapana"
                    })
        
        # -------- COUNTING PHASE (8, 9, 10 Days Logic) --------
        elif started:
            # Jab tak Tithi 1-9 ke beech hai, tab tak count badhao
            if 1 <= tithi <= 9:
                # Handle Vriddhi/Kshaya: Day number is always previous + 1
                day_num = len(navratri_days) + 1
                navratri_days.append({
                    "day_number": day_num,
                    "date": d.strftime("%Y-%m-%d"),
                    "tithi": tithi,
                    "label": f"Navratri Day {day_num}"
                })
            
            # Exit Logic: Agar Sunrise par Dashami (10) aa gayi
            if tithi >= 10:
                print(f">>> END: Dashami detected on {d}. Stopping.")
                break
            
            # Special Exit: Agar Day 9 ho gaya aur agle din Dashami hai
            if tithi == 9:
                next_sun, _ = calculate_sunrise_sunset(dt_input + timedelta(days=1), lat, lon)
                if _tithi_number_at(next_sun) >= 10:
                    print(f">>> END: Navami complete, Dashami tomorrow. Stopping.")
                    break

        d += timedelta(days=1)

    print(f"--- DEBUG END: Total Days Found: {len(navratri_days)} ---\n")

    # 2027 ERROR FIX: List empty check to avoid IndexError
    if not navratri_days:
        return {
            "error": f"Navratri not found for {year}. Check lunar_month_engine.",
            "year": year,
            "days": []
        }

    return {
        "type": navratri_type,
        "year": year,
        "total_days": len(navratri_days),
        "kalash_sthapana_date": navratri_days[0]["date"],
        "days": navratri_days
    }