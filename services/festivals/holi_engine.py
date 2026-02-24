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
    # Feb se start karte hain kyunki aapne sahi kaha, rare case mein Feb mein ho sakti hai
    d = datetime(year, 2, 20).date()
    end_search = datetime(year, 4, 10).date()

    while d <= end_search:
        p = calculate_panchang(d, lat, lon, language)
        sunset_str = p.get("sunset")
        if not sunset_str:
            d += timedelta(days=1)
            continue

        sunset_dt = datetime.strptime(f"{d} {sunset_str}", "%Y-%m-%d %H:%M")
        pradosh_limit = sunset_dt + timedelta(minutes=144)

        # Step 1: Check if Purnima exists at Sunset
        if _tithi_number_at(sunset_dt) != 15:
            d += timedelta(days=1)
            continue

        # Step 2: Bhadra Check
        b_end = _get_bhadra_end_time(sunset_dt)
        
        # 🔥 SPECIAL RULE 2026: 
        # Agar Bhadra poore Pradosh aur poori Raat ko cover kare (B_END next day sunrise ke baad ho)
        # Toh dahan agle din sunset ke baad hoga.
        if b_end > pradosh_limit and b_end.date() > d:
            next_day = d + timedelta(days=1)
            p_next = calculate_panchang(next_day, lat, lon, language)
            sunset_next = p_next.get("sunset")
            sunset_next_dt = datetime.strptime(f"{next_day} {sunset_next}", "%Y-%m-%d %H:%M")

            # Agle din ka Muhurta (Special case for 2026)
            muhurta = {
                "start": sunset_next_dt.strftime("%H:%M"),
                "end": (sunset_next_dt + timedelta(minutes=144)).strftime("%H:%M"),
                "duration": "2 Hours 24 Mins"
            }
            
            return format_response(
                year, next_day, p_next, 
                "Pradosh (Next Day - Vedic Exception)", 
                muhurta, 
                "Bhadra covered the entire night of Purnima, shifting Dahan to the next day's Pradosh."
            )

        # Step 3: Normal Case (Bhadra ends in night or not present)
        # Find Purnima end
        p_end = sunset_dt
        for mins in range(0, 1440, 15):
            if _tithi_number_at(sunset_dt + timedelta(minutes=mins)) != 15:
                p_end = sunset_dt + timedelta(minutes=mins)
                break

        muhurta = calculate_muhurta_window(sunset_dt, p_end, b_end if b_end > sunset_dt else None)
        return format_response(year, d, p, "Standard Pradosh", muhurta, "Dahan performed during Purnima Pradosh.")

    return None