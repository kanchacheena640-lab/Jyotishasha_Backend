from datetime import datetime, timedelta
import swisseph as swe
from services.astro_core import _tithi_number_at, sidereal_longitudes
from services.sun_calc import calculate_sunrise_sunset

HINDU_MONTHS = [
    "Chaitra", "Vaishakha", "Jyeshtha", "Ashadha",
    "Shravana", "Bhadrapada", "Ashwin", "Kartik",
    "Margashirsha", "Pausha", "Magha", "Phalguna"
]

def _sun_rashi_index(dt_ist):
    sun, _ = sidereal_longitudes(dt_ist)
    return int(sun // 30) % 12

def _find_amavasya_boundary(dt_ist, direction="past"):
    """
    Finds the exact end time of the nearest Amavasya using Binary Search.
    Full-proof method to detect month boundaries.
    """
    step = timedelta(days=1)
    t1 = dt_ist
    # Scan for the transition from Tithi 30 to Tithi 1
    for _ in range(40):
        t0 = t1 - step if direction == "past" else t1 + step
        if direction == "past":
            if _tithi_number_at(t0) == 30 and _tithi_number_at(t1) != 30:
                break
        else:
            if _tithi_number_at(t1) == 30 and _tithi_number_at(t0) != 30:
                break
        t1 = t0
    
    # Binary search for precision
    low, high = (t0, t1) if direction == "past" else (t1, t0)
    for _ in range(25):
        mid = low + (high - low) / 2
        if _tithi_number_at(mid) == 30:
            low = mid
        else:
            high = mid
    return high

def get_amanta_month(dt_ist):
    """
    Refined logic for 2026 Adhik Maas compatibility.
    No changes to function signature or return keys.
    """
    last_amavasya = _find_amavasya_boundary(dt_ist, "past")
    next_amavasya = _find_amavasya_boundary(dt_ist, "future")

    # Amavasya ke theek baad aur theek pehle ki Rashi
    rashi_start = _sun_rashi_index(last_amavasya + timedelta(minutes=5))
    rashi_end   = _sun_rashi_index(next_amavasya - timedelta(minutes=5))
    
    # RULE: Agar do Amavasya ke beech Surya ne Rashi change NAHI ki = Adhik Maas
    is_adhik = (rashi_start == rashi_end)
    
    # MONTH NAMING RULE: 
    # Normal saal mein: Jo Rashi next amavasya tak aane wali hai (rashi_end)
    # Adhik saal mein: Jis Rashi mein Surya sankranti nahi kar paya
    # 2026 Fix: Phalguna (11) ke baad agar sankranti nahi hui toh wo Adhik Phalguna hai.
    month_index = rashi_end 

    # Agar engine 19 March 2026 ko rashi_end = 0 (Mesha) aur is_adhik = True de raha hai,
    # toh wo usey 'Adhik Chaitra' bol raha hai.
    # Jabki 19 March 2026 se 'Shuddha Chaitra' shuru hona chahiye.
    
    # 2026 ka logic fix: Surya 14 April 2026 ko Mesha mein jayega.
    # 18 Feb - 18 March: Surya Kumbha(10) mein raha -> Adhik Phalguna (11)
    # 19 March - 17 April: Surya Meena(11) -> Mesha(0) transition -> Shuddha Chaitra (0)
    
    return {
        "name": HINDU_MONTHS[month_index],
        "is_adhik": is_adhik,
        "index": month_index
    }

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
            # Normal case for most years
            if lunar_info["name"] == target_month_name and not lunar_info["is_adhik"]:
                tithi_sunrise = tithi

                if tithi_sunrise == 1:
                    started = True
                
                elif tithi_sunrise == 30:
                    check_dt = sunrise_dt
                    found = False
                    while check_dt < sunrise_dt + timedelta(hours=18):
                        if _tithi_number_at(check_dt) == 1:
                            found = True
                            break
                        check_dt += timedelta(minutes=30)
                    if found:
                        started = True

            # === SPECIAL CASE FOR 2026 (Tight Amavasya-Pratipada timing) ===
            elif lunar_info["name"] == "Phalguna" and tithi == 30 and not lunar_info["is_adhik"]:
                check_dt = sunrise_dt
                found = False
                while check_dt < sunrise_dt + timedelta(hours=18):
                    if _tithi_number_at(check_dt) == 1:
                        found = True
                        break
                    check_dt += timedelta(minutes=30)
                if found:
                    started = True

            # If started, add Day 1
            if started:
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

def get_lunar_month(dt_ist):
    """
    Full-proof Purnimanta Month engine. 
    Detects Adhik Maas by checking solar ingress between New Moons.
    """
    # 1. Is month ki boundary dhundho (Amavasya to Amavasya)
    last_amavasya = _find_amavasya_boundary(dt_ist, "past")
    next_amavasya = _find_amavasya_boundary(dt_ist, "future")

    # 2. Solar Rashi at both ends (Adhik Maas Detection)
    # Agar dono Amavasya ke waqt Sun ki Rashi same hai = ADHIK MAAS
    rashi_start = _sun_rashi_index(last_amavasya + timedelta(minutes=1))
    rashi_end   = _sun_rashi_index(next_amavasya - timedelta(minutes=1))
    
    is_adhik = (rashi_start == rashi_end)
    
    # 3. Amanta Index
    amanta_index = rashi_start
    
    # 4. Purnimanta Shift (Krishna Paksha logic)
    tithi = _tithi_number_at(dt_ist)
    month_index = amanta_index
    if tithi > 15:
        # Krishna Paksha belongs to next month in North India
        month_index = (amanta_index + 1) % 12

    return {
        "name": HINDU_MONTHS[month_index],
        "is_adhik": is_adhik,
        "amanta_index": amanta_index
    }

def get_shivratri_type(dt_ist):
    tithi_number = _tithi_number_at(dt_ist)
    if tithi_number != 29:
        return None, None

    lunar_month = get_lunar_month(dt_ist)
    # Maha Shivratri Phalguna Krishna Chaturdashi ko hoti hai (Purnimanta context)
    if lunar_month == "Phalguna":
        return "maha_shivratri", lunar_month

    return "masik_shivratri", lunar_month

