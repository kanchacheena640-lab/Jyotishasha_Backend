from datetime import datetime, timedelta
# Saare zaroori services aur engines yahan hain
from services.panchang_engine import calculate_panchang, _tithi_number_at, _karan_at
from services.lunar_month_engine import get_lunar_month

def _get_bhadra_end_time(start_time, limit_hours=18):
    """Bhadra (Vishti Karana) kab khatam ho rahi hai, 5-minute precision se check karega."""
    check_time = start_time
    limit_time = start_time + timedelta(hours=limit_hours)
    while check_time <= limit_time:
        k_name, _ = _karan_at(check_time)
        if k_name != "Vishti (Bhadra)":
            return check_time
        check_time += timedelta(minutes=5)
    return None

def format_response(year, dahan_date, p_data, method):
    """Final output ko standard format mein lane ke liye helper."""
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

def detect_holi(year, lat, lon, language="en"):
    # Holi window search (late Feb to early April)
    d = datetime(year, 2, 20).date()
    end_search = datetime(year, 4, 10).date()

    while d <= end_search:
        # 1. Month Check: Holi sirf Phalguna mein honi chahiye (2027 fix)
        l_month = get_lunar_month(datetime.combine(d, datetime.min.time()))
        if l_month not in ("Phalguna", "फाल्गुन"):
            d += timedelta(days=1)
            continue

        p = calculate_panchang(d, lat, lon, language)
        sunset_str = p.get("sunset")
        if not sunset_str:
            d += timedelta(days=1); continue

        sunset_dt = datetime.strptime(f"{d} {sunset_str}", "%Y-%m-%d %H:%M")

        # 2. Check if Day 1 has Purnima at Sunset
        # (Using a small 3-hour buffer for special cases like 2026)
        is_purnima = False
        if _tithi_number_at(sunset_dt) == 15:
            is_purnima = True
        elif _tithi_number_at(sunset_dt - timedelta(hours=3)) == 15:
            is_purnima = True

        if is_purnima:
            karan, _ = _karan_at(sunset_dt)
            
            # 3. Handle Bhadra (Vishti Karan)
            if karan == "Vishti (Bhadra)":
                # Day 2 check karo
                next_day = d + timedelta(days=1)
                p_next = calculate_panchang(next_day, lat, lon, language)
                sunset_next_dt = datetime.strptime(f"{next_day} {p_next.get('sunset')}", "%Y-%m-%d %H:%M")
                
                # Logic: Agar Day 2 Sunset par Purnima bachi hai (2026 case)
                if _tithi_number_at(sunset_next_dt) == 15 or _tithi_number_at(sunset_next_dt - timedelta(hours=2)) == 15:
                    return format_response(year, next_day, p_next, "Day 2 (Bhadra Avoidance)")
                else:
                    # Logic: Agar Day 2 Sunset tak Purnima nahi bachi (2027 case)
                    # Dahan Day 1 ki raat ko hi hoga after Bhadra ends
                    b_end = _get_bhadra_end_time(sunset_dt)
                    return format_response(year, d, p, f"Day 1 Night (Post-Bhadra: {b_end.strftime('%H:%M')})")
            
            else:
                # No Bhadra, Standard Case
                return format_response(year, d, p, "Standard Pradosh")

        d += timedelta(days=1)
    return None