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
    # Holi search range
    d = datetime(year, 2, 20).date()
    end_search = datetime(year, 4, 10).date()

    while d <= end_search:
        # Step 1: Month filter
        l_month = get_lunar_month(datetime.combine(d, datetime.min.time()))
        if l_month not in ("Phalguna", "फाल्गुन"):
            d += timedelta(days=1); continue

        p = calculate_panchang(d, lat, lon, language)
        sunset_str = p.get("sunset")
        if not sunset_str:
            d += timedelta(days=1); continue

        sunset_dt = datetime.strptime(f"{d} {sunset_str}", "%Y-%m-%d %H:%M")

        # Step 2: Purnima check (with buffer)
        if _tithi_number_at(sunset_dt) == 15 or _tithi_number_at(sunset_dt - timedelta(hours=3)) == 15:
            
            # Purnima end time nikalne ka iterative logic
            p_end = sunset_dt
            for mins in range(0, 1440, 15):
                check_t = sunset_dt + timedelta(minutes=mins)
                if _tithi_number_at(check_t) != 15:
                    p_end = check_t
                    break

            karan, _ = _karan_at(sunset_dt)
            
            # Step 3: Bhadra handling
            if karan == "Vishti (Bhadra)":
                b_end = _get_bhadra_end_time(sunset_dt)
                next_day = d + timedelta(days=1)
                p_next_data = calculate_panchang(next_day, lat, lon, language)
                sunset_next_dt = datetime.strptime(f"{next_day} {p_next_data.get('sunset')}", "%Y-%m-%d %H:%M")
                
                # Check for Day 2 shifting (2026 rule)
                if _tithi_number_at(sunset_next_dt) == 15 or _tithi_number_at(sunset_next_dt - timedelta(hours=2)) == 15:
                    p_end_next = sunset_next_dt
                    for m in range(0, 300, 5): 
                        if _tithi_number_at(sunset_next_dt + timedelta(minutes=m)) != 15:
                            p_end_next = sunset_next_dt + timedelta(minutes=m)
                            break
                    
                    muhurta = calculate_muhurta_window(sunset_next_dt, p_end_next)
                    return format_response(year, next_day, p_next_data, "Day 2 (Bhadra Avoidance)", muhurta, "Holi shifted to Day 2 due to Bhadra on Day 1.")
                
                else:
                    # No Day 2 option (2027 rule), stick to Day 1 Night
                    muhurta = calculate_muhurta_window(sunset_dt, p_end, b_end)
                    return format_response(year, d, p, "Day 1 Night (Post-Bhadra)", muhurta, f"Bhadra ended at {b_end.strftime('%H:%M')}, hence night dahan.")
            
            else:
                # No Bhadra, everything is clean
                muhurta = calculate_muhurta_window(sunset_dt, p_end)
                return format_response(year, d, p, "Standard Pradosh", muhurta, "Dahan during standard Pradosh Kaal.")

        d += timedelta(days=1)
    return None