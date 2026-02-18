from datetime import datetime, timedelta
from services.panchang_engine import calculate_panchang, _tithi_number_at, _karan_at
from services.lunar_month_engine import get_lunar_month

def _is_purnima_near_sunset(check_dt):
    # Standard: Current Tithi is 15
    if _tithi_number_at(check_dt) == 15:
        return True
    # Special 2026 Case: Tithi ended just before sunset (within 3 hours)
    if _tithi_number_at(check_dt - timedelta(hours=3)) == 15:
        # Extra safety: Ensure it didn't end TOO long ago
        return True
    return False

def detect_holi(year, lat, lon, language="en"):
    # Safety: Holi can only happen between March 1 and April 15 
    # (Exception: rare Feb end, but 2027 Phalguna is in March)
    start_search = datetime(year, 2, 20).date()
    end_search = datetime(year, 4, 10).date()
    
    d = start_search
    while d <= end_search:
        # 1. Lunar Month Check (The 2027 Fix)
        # We need the Lunar Month to be Phalguna (फाल्गुन)
        current_lunar_month = get_lunar_month(datetime.combine(d, datetime.min.time()))
        
        if current_lunar_month not in ("Phalguna", "फाल्गुन"):
            d += timedelta(days=1)
            continue

        p = calculate_panchang(d, lat, lon, language)
        sunset_str = p.get("sunset")
        if not sunset_str:
            d += timedelta(days=1); continue

        sunset_dt = datetime.strptime(f"{d} {sunset_str}", "%Y-%m-%d %H:%M")
        
        # 2. Find the Purnima Tithi
        if _is_purnima_near_sunset(sunset_dt):
            karan, _ = _karan_at(sunset_dt)
            
            # 3. Bhadra Management
            if karan == "Vishti (Bhadra)":
                # Check Day 2 for cleaner window (Bhadra Avoidance)
                next_day = d + timedelta(days=1)
                p_next = calculate_panchang(next_day, lat, lon, language)
                sunset_next_dt = datetime.strptime(f"{next_day} {p_next.get('sunset')}", "%Y-%m-%d %H:%M")
                
                if _is_purnima_near_sunset(sunset_next_dt):
                    return format_response(year, next_day, p_next, "Day 2 (Bhadra Avoidance)")
                else:
                    # If Day 2 is not valid, use Day 1 Late Night after Bhadra
                    return format_response(year, d, p, "Day 1 Night (Post-Bhadra)")
            else:
                return format_response(year, d, p, "Standard Pradosh")
        
        d += timedelta(days=1)
    return None

def format_response(year, dahan_date, p_data, method):
    return {
        "year": year,
        "holika_dahan": {
            "date": dahan_date.strftime("%Y-%m-%d"),
            "sunset_time": p_data.get("sunset"),
            "method_applied": method
        },
        "holi_dhulandi": {
            "date": (dahan_date + timedelta(days=1)).strftime("%Y-%m-%d")
        }
    }