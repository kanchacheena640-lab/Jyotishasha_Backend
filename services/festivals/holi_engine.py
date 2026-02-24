from datetime import datetime, timedelta
# Panchang engine se sirf wahi functions liye hain jo aapke paas available hain
from services.panchang_engine import calculate_panchang, _tithi_number_at, _karan_at
from services.lunar_month_engine import get_lunar_month

def _get_bhadra_end_time(start_time, limit_hours=18):
    """Bhadra kab khatam ho rahi hai, 5-minute check se nikalta hai."""
    check_time = start_time
    limit_time = start_time + timedelta(hours=limit_hours)
    while check_time <= limit_time:
        k_name, _ = _karan_at(check_time)
        if k_name != "Vishti (Bhadra)":
            return check_time
        check_time += timedelta(minutes=5)
    return start_time + timedelta(hours=12)

def calculate_muhurta_window(sunset_dt, purnima_end_dt, bhadra_end_dt=None):
    """Exact dahan ka samay nikalne ka logic."""
    start_time = sunset_dt
    if bhadra_end_dt and bhadra_end_dt > sunset_dt:
        start_time = bhadra_end_dt
    
    # Pradosh limit: Sunset ke 2 ghante 24 min tak
    pradosh_limit = sunset_dt + timedelta(minutes=144)
    end_time = min(purnima_end_dt, pradosh_limit)
    
    # Rare Case: Agar window negative ho jaye (2026), toh minimum 15 min ka window
    if start_time >= end_time:
        end_time = start_time + timedelta(minutes=15)

    return {
        "start": start_time.strftime("%H:%M"),
        "end": end_time.strftime("%H:%M"),
        "duration": str(end_time - start_time).split('.')[0]
    }

def format_response(year, d_date, p_data, method, muhurta, extra):
    """SSR aur Google Search ke liye structured output."""
    return {
        "year": year,
        "holika_dahan": {
            "date": d_date.strftime("%Y-%m-%d"),
            "sunset": p_data.get("sunset"),
            "muhurta": f"{muhurta['start']} to {muhurta['end']}",
            "duration": muhurta['duration'],
            "method": method,
            "note": extra
        },
        "holi_dhulandi": {
            "date": (d_date + timedelta(days=1)).strftime("%Y-%m-%d")
        }
    }

def detect_holi(year, lat, lon, language="en"):
    # Holi hamesha Phalguna Purnima ko hoti hai
    # Hum March 1 se April 10 tak search karenge
    d = datetime(year, 3, 1).date()
    end_search = datetime(year, 4, 10).date()

    while d <= end_search:
        p = calculate_panchang(d, lat, lon, language)
        sunset_str = p.get("sunset")
        if not sunset_str:
            d += timedelta(days=1)
            continue

        sunset_dt = datetime.strptime(f"{d} {sunset_str}", "%Y-%m-%d %H:%M")
        
        # Pradosh Kaal: Sunset se 2 ghante 24 min tak
        pradosh_end = sunset_dt + timedelta(minutes=144)
        
        # 🔥 FIX 1: Sirf sunset nahi, Pradosh ke kisi bhi hisse mein Purnima honi chahiye
        # Check if Purnima (15) exists during Pradosh
        is_purnima_in_pradosh = False
        purnima_entry_time = None
        
        for m in range(0, 145, 15):
            if _tithi_number_at(sunset_dt + timedelta(minutes=m)) == 15:
                is_purnima_in_pradosh = True
                if not purnima_entry_time:
                    purnima_entry_time = sunset_dt + timedelta(minutes=m)
                break
        
        if not is_purnima_in_pradosh:
            d += timedelta(days=1)
            continue

        # Find exact Purnima end time
        p_end = sunset_dt
        for mins in range(0, 2000, 15):
            check_t = sunset_dt + timedelta(minutes=mins)
            if _tithi_number_at(check_t) != 15:
                p_end = check_t
                break

        # 🔥 BHADRA CHECK
        b_end = _get_bhadra_end_time(sunset_dt)
        
        # Bhadra active logic
        bhadra_in_pradosh = False
        if b_end > sunset_dt:
            bhadra_in_pradosh = True

        # Decision Logic
        if bhadra_in_pradosh and b_end > pradosh_end:
            # Bhadra poore pradosh ko cover kar rahi hai
            # Check if Purnima is still there after Bhadra
            if _tithi_number_at(b_end + timedelta(minutes=1)) == 15:
                # Dahan after Bhadra late night
                muhurta = calculate_muhurta_window(sunset_dt, p_end, b_end)
                return format_response(year, d, p, "Late Night (Post-Bhadra)", muhurta, "Bhadra covered Pradosh, so Dahan performed after Bhadra end.")
            else:
                # Purnima khatam ho gayi, shift to next day (agar next day sunset pe Purnima ho)
                # Ye tabhi hota hai jab Purnima 2 din split ho
                d += timedelta(days=1)
                continue
        else:
            # Best Case: No Bhadra or Bhadra ends within Pradosh
            muhurta = calculate_muhurta_window(sunset_dt, p_end, b_end if bhadra_in_pradosh else None)
            return format_response(year, d, p, "Standard Pradosh", muhurta, "Holika Dahan during auspicious Pradosh Kaal.")

    return None