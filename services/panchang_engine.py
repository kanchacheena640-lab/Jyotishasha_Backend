from datetime import datetime, timedelta
from services.astro_core import sidereal_longitudes, _tithi_number_at
from services.panchang_engine import calculate_sunrise_sunset

def detect_navratri_expert(year, lat, lon, navratri_type="chaitra"):
    # 1. Vedic Season Window
    if navratri_type == "chaitra":
        # March 1 se scan shuru (Meena Sankranti window)
        d = datetime(year, 3, 1).date()
        search_end = datetime(year, 4, 25).date()
    else:
        # Sept 1 se scan shuru (Kanya Sankranti window)
        d = datetime(year, 9, 1).date()
        search_end = datetime(year, 10, 30).date()

    navratri_days = []
    started = False
    
    # Render safety: Max 60 days scan
    for _ in range(60):
        if d > search_end: break
        
        dt_ist = datetime.combine(d, datetime.min.time())
        sunrise_dt, _ = calculate_sunrise_sunset(d, lat, lon)
        
        # 2. Get Sun Rashi (Solar Month) - Sabse bada logic yahi hai
        sun_long, _ = sidereal_longitudes(sunrise_dt)
        sun_rashi = int(sun_long // 30) + 1 # 1:Mesh, 12:Meena
        
        # 3. Get Tithi at Sunrise
        tithi = _tithi_number_at(sunrise_dt)

        if not started:
            # PURE SHASTRIYA CONDITION:
            # Chaitra Navratri = Sun in Meena (12) AND Tithi is 1
            # Ashwin Navratri = Sun in Kanya (6) AND Tithi is 1
            target_rashi = 12 if navratri_type == "chaitra" else 6
            
            if tithi == 1 and sun_rashi == target_rashi:
                # Double Check: Kal Amavasya thi?
                yesterday_sunrise = sunrise_dt - timedelta(days=1)
                if _tithi_number_at(yesterday_sunrise) in [30, 29]:
                    started = True
                    navratri_days.append({
                        "day_number": 1,
                        "date": d.strftime("%Y-%m-%d"),
                        "tithi": 1,
                        "label": "Kalash Sthapana"
                    })
        else:
            # Continuation (Day 2 to 9)
            if 1 <= tithi <= 9:
                # Handle Tithi Kshaya/Vriddhi by keeping continuous count
                day_num = len(navratri_days) + 1
                navratri_days.append({
                    "day_number": day_num,
                    "date": d.strftime("%Y-%m-%d"),
                    "tithi": tithi,
                    "label": f"Navratri Day {day_num}"
                })
                
                if tithi == 9:
                    # Final check: Next sunrise par 9 toh nahi? (Vriddhi case)
                    next_sunrise = sunrise_dt + timedelta(days=1)
                    if _tithi_number_at(next_sunrise) != 9:
                        break # Perfect 9 days reached
            else:
                break # Dashami reached

        d += timedelta(days=1)

    return {
        "type": navratri_type,
        "year": year,
        "total_days": len(navratri_days),
        "kalash_sthapana_date": navratri_days[0]["date"] if navratri_days else None,
        "days": navratri_days
    }