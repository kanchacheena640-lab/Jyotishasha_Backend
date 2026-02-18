from datetime import datetime, timedelta
# Assuming these services are available
from services.panchang_engine import calculate_panchang, _tithi_number_at, _karan_at

def _get_bhadra_end_time(start_time, limit_hours=18):
    check_time = start_time
    limit_time = start_time + timedelta(hours=limit_hours)
    while check_time <= limit_time:
        k_name, _ = _karan_at(check_time)
        if k_name != "Vishti (Bhadra)":
            return check_time
        check_time += timedelta(minutes=5)
    return None

def _is_purnima_near_sunset(check_dt):
    """
    Special Rule: Checks if Purnima is active OR was active 
    very close to sunset (for cases like 2026).
    """
    # If currently Purnima
    if _tithi_number_at(check_dt) == 15:
        return True
    
    # Special Case: If Purnima ended within last 2 hours of Sunset
    # (Matches Drik Panchang logic where 5:07 PM end and 6:08 PM Sunset is valid)
    if _tithi_number_at(check_dt - timedelta(hours=2)) == 15:
        return True
        
    return False

def detect_holi(year, lat, lon, language="en"):
    # Target window for Phalguna month
    d = datetime(year, 2, 20).date()
    end_date = datetime(year, 3, 25).date()

    while d <= end_date:
        p = calculate_panchang(d, lat, lon, language)
        sunset_str = p.get("sunset")
        if not sunset_str:
            d += timedelta(days=1); continue

        sunset_dt = datetime.strptime(f"{d} {sunset_str}", "%Y-%m-%d %H:%M")
        
        # 1. Check if it's Purnima around Sunset
        if _is_purnima_near_sunset(sunset_dt):
            karan, _ = _karan_at(sunset_dt)
            
            # 2. Check for Bhadra (Vishti)
            if karan == "Vishti (Bhadra)":
                # Bhadra is active. Check Day 2.
                next_day = d + timedelta(days=1)
                p_next = calculate_panchang(next_day, lat, lon, language)
                sunset_next_dt = datetime.strptime(f"{next_day} {p_next.get('sunset')}", "%Y-%m-%d %H:%M")
                
                # SPECIAL CASE: 2026 handling
                # Even if Purnima ends at 5:07 PM and Sunset is 6:08 PM, it's valid for Day 2.
                if _is_purnima_near_sunset(sunset_next_dt):
                    # Day 2 is valid because Day 1 was blocked by Bhadra
                    return format_response(year, next_day, p_next, "Day 2 (Bhadra Avoidance)")
                else:
                    # If Day 2 is not valid at all, fallback to Day 1 after Bhadra
                    b_end = _get_bhadra_end_time(sunset_dt)
                    return format_response(year, d, p, f"Day 1 Night (Post-Bhadra: {b_end.strftime('%H:%M')})")
            else:
                # No Bhadra, Purnima active at Sunset
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