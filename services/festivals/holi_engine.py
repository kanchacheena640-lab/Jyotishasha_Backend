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
    # Range safe rakhte hain
    d = datetime(year, 2, 20).date()
    end_search = datetime(year, 4, 15).date()

    while d <= end_search:
        # 1. Lunar Month Check (Aapke engine ke keys ke hisab se)
        # DHAYAN DEIN: Yahan sirf (d) bheja hai taaki crash na ho
        try:
            month_info = get_lunar_month(d) 
            # Aapka engine "name" key bhej raha hai
            lunar_month = month_info.get("name", "") 
        except Exception as e:
            print(f"Lunar Engine Error: {e}")
            d += timedelta(days=1)
            continue

        # 2. Filter: Holi Phalguna mein hoti hai, par safety ke liye 
        # 2027 jaise cases mein Chaitra boundary ko bhi allow karte hain filter ke liye
        if "Phalguna" not in lunar_month and "Chaitra" not in lunar_month:
            d += timedelta(days=1)
            continue

        p = calculate_panchang(d, lat, lon, language)
        sunset_str = p.get("sunset")
        if not sunset_str:
            d += timedelta(days=1)
            continue

        sunset_dt = datetime.strptime(f"{d} {sunset_str}", "%Y-%m-%d %H:%M")
        
        # 3. Exact Tithi Check (Holi hamesha Purnima yaani 15 ko hoti hai)
        # Pradosh window (sunset ke baad 2.5 ghante) mein check karein
        is_purnima_in_pradosh = False
        for mins in range(0, 150, 5):
            if _tithi_number_at(sunset_dt + timedelta(minutes=mins)) == 15:
                is_purnima_in_pradosh = True
                break
        
        if not is_purnima_in_pradosh:
            d += timedelta(days=1)
            continue

        # --- Yahan se Muhurta aur Bhadra ka logic shuru hota hai ---
        p_end = sunset_dt
        for mins in range(0, 2000, 10):
            if _tithi_number_at(sunset_dt + timedelta(minutes=mins)) != 15:
                p_end = sunset_dt + timedelta(minutes=mins)
                break

        b_end = _get_bhadra_end_time(sunset_dt, limit_hours=30)
        pradosh_limit = sunset_dt + timedelta(minutes=144)

        # Special Case 2026: Bhadra covers full night
        if b_end > pradosh_limit and b_end.date() > d:
            next_day = d + timedelta(days=1)
            p_next = calculate_panchang(next_day, lat, lon, language)
            sunset_next_dt = datetime.strptime(f"{next_day} {p_next.get('sunset')}", "%Y-%m-%d %H:%M")
            muhurta = {"start": sunset_next_dt.strftime("%H:%M"), "end": (sunset_next_dt + timedelta(minutes=144)).strftime("%H:%M"), "duration": "2 Hours 24 Mins"}
            return format_response(year, next_day, p_next, "Pradosh (Vedic Exception)", muhurta, "Dahan shifted due to Bhadra.")

        muhurta = calculate_muhurta_window(sunset_dt, p_end, b_end if b_end > sunset_dt else None)
        return format_response(year, d, p, "Pradosh/Late Night", muhurta, "Holika Dahan performed during Phalguna Purnima.")

    return None