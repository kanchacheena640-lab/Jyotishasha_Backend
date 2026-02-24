from datetime import datetime, timedelta
from services.panchang_engine import calculate_sunrise_sunset
from services.astro_core import _tithi_number_at


def detect_navratri(year, lat, lon, navratri_type="chaitra"):
    if navratri_type == "chaitra":
        # Chaitra Navratri range
        d = datetime(year, 3, 1).date()
        search_end = datetime(year, 4, 20).date()
    else:
        # Ashwin Navratri range
        d = datetime(year, 9, 1).date()
        search_end = datetime(year, 10, 30).date()

    navratri_days = []
    started = False
    
    while d <= search_end:
        dt_input = datetime.combine(d, datetime.min.time())
        sunrise_dt, _ = calculate_sunrise_sunset(dt_input, lat, lon)
        tithi = _tithi_number_at(sunrise_dt)

        if not started:
            # PURE LOGIC: Navratri Day 1 tab shuru hoga jab Sunrise par Tithi 1 ho
            if tithi == 1:
                # Confirming it's Shukla Paksha: 
                # Kal ki tithi 28, 29 ya 30 honi chahiye (Amavasya phase)
                yesterday_sunrise = sunrise_dt - timedelta(days=1)
                tithi_yesterday = _tithi_number_at(yesterday_sunrise)
                
                if tithi_yesterday in [28, 29, 30]:
                    started = True
                    navratri_days.append({
                        "day_number": 1,
                        "date": d.strftime("%Y-%m-%d"),
                        "tithi": 1,
                        "label": "Kalash Sthapana"
                    })
        else:
            # Continuation (Day 2 to 9)
            # Jab tak tithi 1 se 9 ke beech hai, tab tak count badhao
            if 1 <= tithi <= 9:
                # Har naye din ke liye total count + 1
                current_day_count = len(navratri_days) + 1
                
                navratri_days.append({
                    "day_number": current_day_count,
                    "date": d.strftime("%Y-%m-%d"),
                    "tithi": tithi,
                    "label": f"Navratri Day {current_day_count}"
                })
                
                if tithi == 9:
                    # Check: Kya agle din sunrise par bhi 9 hai? (Vriddhi Case)
                    next_day_sunrise = sunrise_dt + timedelta(days=1)
                    if _tithi_number_at(next_day_sunrise) != 9:
                        break
            else:
                # Dashami (10) aa gayi, Navratri over
                break

        d += timedelta(days=1)

    return {
        "type": navratri_type,
        "year": year,
        "total_days": len(navratri_days),
        "kalash_sthapana_date": navratri_days[0]["date"] if navratri_days else None,
        "days": navratri_days
    }