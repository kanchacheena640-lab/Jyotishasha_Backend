from datetime import datetime, timedelta
from services.panchang_engine import calculate_sunrise_sunset
from services.astro_core import _tithi_number_at
from services.lunar_month_engine import get_lunar_month


def detect_navratri(year, lat, lon, navratri_type="chaitra"):
    # Sirf wide range di hai search ke liye, logic andar hai
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
    
    d = start_range
    while d <= end_range:
        dt_input = datetime.combine(d, datetime.min.time())
        # 1. Sunrise nikalna astronomical logic ke liye zaroori hai
        sunrise_dt, _ = calculate_sunrise_sunset(dt_input, lat, lon)
        
        # 2. Sunrise ke waqt ki Tithi
        tithi = _tithi_number_at(sunrise_dt)
        
        # 3. Lunar Month Engine se Month Name
        lunar_data = get_lunar_month(sunrise_dt)
        lunar_month = lunar_data["name"]
        
        # 4. PURE LOGIC: Navratri Day 1 tabhi shuru hoga jab:
        # Month sahi ho AUR Tithi 1 ho AUR wo SHUKLA PAKSHA ho.
        # Shukla Paksha check karne ka pure logic: 
        # Tithi 1 at Sunrise after an Amavasya (Tithi 30).
        
        if not started:
            if lunar_month == target_month and tithi == 1:
                # Check pichli raat ki tithi (to confirm it's Shukla Pratipada)
                # Shukla Pratipada ke theek pehle Amavasya (30) honi chahiye
                yesterday_sunrise = sunrise_dt - timedelta(days=1)
                tithi_yesterday = _tithi_number_at(yesterday_sunrise)
                
                # Agar kal 30 thi ya aaj sunrise se thoda pehle 30 khatam hui hai
                if tithi_yesterday == 30 or tithi_yesterday == 29:
                    started = True
                    navratri_days.append({
                        "day_number": 1,
                        "date": d.strftime("%Y-%m-%d"),
                        "tithi": 1,
                        "label": "Kalash Sthapana"
                    })
        
        # 5. CONTINUE NAVRATRI (Sunrise Ownership Rule)
        elif started:
            # Navratri tab tak chalegi jab tak Sunrise par Tithi 9 khatam na ho jaye
            # Ya phir mahina na badal jaye (extreme case)
            if 1 <= tithi <= 9:
                # Vriddhi/Kshaya Logic
                last_day = navratri_days[-1]
                if tithi == last_day["tithi"]:
                    # Tithi Vriddhi: Tithi repeat ho rahi hai
                    day_num = last_day["day_number"] + 1
                else:
                    # Normal flow ya Tithi Kshaya (ek skip ho gayi toh bhi count agla hi hoga)
                    day_num = last_day["day_number"] + 1

                navratri_days.append({
                    "day_number": day_num,
                    "date": d.strftime("%Y-%m-%d"),
                    "tithi": tithi,
                    "label": f"Navratri Day {day_num}"
                })
                
                # Stop if we reached Tithi 9 (but check if next day is 10)
                if tithi == 9:
                    # Double check: Kya agle sunrise par 10 hai? 
                    # Agar agle sunrise par bhi 9 rahi, toh loop chalne denge (Vriddhi)
                    next_sunrise = sunrise_dt + timedelta(days=1)
                    if _tithi_number_at(next_sunrise) != 9:
                        break
            else:
                # Agar Tithi 10 aa gayi, Navratri khatam
                break

        d += timedelta(days=1)

    return {
        "type": navratri_type,
        "year": year,
        "total_days": len(navratri_days),
        "days": navratri_days
    }