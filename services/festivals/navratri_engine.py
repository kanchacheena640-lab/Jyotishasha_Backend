from datetime import datetime, timedelta
from services.panchang_engine import calculate_sunrise_sunset
from services.astro_core import _tithi_number_at, sidereal_longitudes # <--- Ye line update karni hai

def detect_navratri(year, lat, lon, navratri_type="chaitra"):
    # 1. Search window set karte hain
    if navratri_type == "chaitra":
        d = datetime(year, 3, 1).date()
        search_end = datetime(year, 4, 25).date()
        target_rashi = 12  # Meena Rashi (Must for Chaitra Navratri)
    else:
        d = datetime(year, 9, 1).date()
        search_end = datetime(year, 10, 30).date()
        target_rashi = 6   # Kanya Rashi (Must for Ashwin Navratri)

    navratri_days = []
    started = False
    
    while d <= search_end:
        dt_input = datetime.combine(d, datetime.min.time())
        # Aapke existing engine se sunrise aur tithi nikalte hain
        sunrise_dt, _ = calculate_sunrise_sunset(d, lat, lon)
        tithi = _tithi_number_at(sunrise_dt)
        
        # 2. Sun Rashi check (Swiss Eph ka use karke sidereal_longitudes se)
        sun_long, _ = sidereal_longitudes(sunrise_dt)
        sun_rashi = int(sun_long // 30) + 1

        if not started:
            # Condition: Sahi Rashi honi chahiye aur Tithi 1
            if tithi == 1 and sun_rashi == target_rashi:
                # Confirming Shukla Paksha (Amavasya phase check)
                yesterday_sunrise = sunrise_dt - timedelta(days=1)
                if _tithi_number_at(yesterday_sunrise) in [29, 30]:
                    started = True
        
        if started:
            # Counting days (1 to 9)
            day_num = len(navratri_days) + 1
            
            # Agar tithi 10 aa gayi sunrise par, toh Navratri over
            if tithi == 10:
                break
                
            navratri_days.append({
                "day_number": day_num,
                "date": d.strftime("%Y-%m-%d"),
                "tithi": tithi,
                "label": "Kalash Sthapana" if day_num == 1 else f"Navratri Day {day_num}"
            })
            
            # Stop condition: 9 din pure hone par check
            if day_num >= 9:
                # Check for Tithi Vriddhi (next sunrise must not be Tithi 9)
                next_sunrise = sunrise_dt + timedelta(days=1)
                if _tithi_number_at(next_sunrise) != 9:
                    break

        d += timedelta(days=1)

    return {
        "days": navratri_days,
        "kalash_sthapana_date": navratri_days[0]["date"] if navratri_days else None,
        "total_days": len(navratri_days),
        "type": navratri_type,
        "year": year
    }