from datetime import datetime, timedelta
from services.panchang_engine import calculate_sunrise_sunset
from services.astro_core import _tithi_number_at
from services.lunar_month_engine import get_amanta_month
from services.panchang_engine import calculate_panchang


NAVRATRI_DAY_MAP = {
    1: "Shailputri",
    2: "Brahmacharini",
    3: "Chandraghanta",
    4: "Kushmanda",
    5: "Skandamata",
    6: "Katyayani",
    7: "Kalaratri",
    8: "Mahagauri",
    9: "Siddhidatri"
}

def detect_navratri(year, lat, lon, navratri_type="chaitra"):

    
    target_month_name = "Chaitra" if navratri_type == "chaitra" else "Ashwin"

    start_date = datetime(year, 3, 1).date() if navratri_type == "chaitra" else datetime(year, 9, 1).date()
    d = start_date
    search_end = d + timedelta(days=80)

    navratri_days = []
    started = False

    while d <= search_end:

        
        dt_input = datetime.combine(d, datetime.min.time())
        sunrise_dt, _ = calculate_sunrise_sunset(dt_input, lat, lon)

        tithi_sunrise = _tithi_number_at(sunrise_dt)
        tithi_6h = _tithi_number_at(sunrise_dt + timedelta(hours=6))
        tithi_12h = _tithi_number_at(sunrise_dt + timedelta(hours=12))

        lunar_info = get_amanta_month(sunrise_dt)

        # -------- PREVIOUS DAY DEBUG --------
        prev_date = d - timedelta(days=1)
        prev_sunrise, _ = calculate_sunrise_sunset(
            datetime.combine(prev_date, datetime.min.time()),
            lat, lon
        )

        prev_tithi = _tithi_number_at(prev_sunrise)
        prev_month = get_amanta_month(prev_sunrise)["name"]

        # -------- START CONDITION CHECK --------
        pratipada_present = (
            tithi_sunrise == 1
            or tithi_6h == 1
            or tithi_12h == 1
        )

        if not started:

            # -------- NORMAL RULE --------
            # Sunrise पर Pratipada मिले
            if (
                lunar_info["name"] == target_month_name
                and tithi_sunrise == 1
            ):
                
                started = True

                navratri_days.append({
                    "day_number": 1,
                    "date": d.strftime("%Y-%m-%d"),
                    "tithi": 1,
                    "label": "Kalash Sthapana"
                })

            # -------- RARE EDGE CASE (Like 2026) --------
            else:

                # Check if TODAY sunrise = 30 (Amavasya end)
                if tithi_sunrise == 30:

                    # Check if during today Pratipada occurred
                    tithi_6h = _tithi_number_at(sunrise_dt + timedelta(hours=6))
                    tithi_12h = _tithi_number_at(sunrise_dt + timedelta(hours=12))

                    pratipada_inside_day = (
                        tithi_6h == 1 or tithi_12h == 1
                    )

                    # Check next day sunrise
                    next_date = d + timedelta(days=1)
                    next_sunrise, _ = calculate_sunrise_sunset(
                        datetime.combine(next_date, datetime.min.time()),
                        lat, lon
                    )

                    next_tithi = _tithi_number_at(next_sunrise)
                    next_month = get_amanta_month(next_sunrise)["name"]

                    if (
                        pratipada_inside_day
                        and next_tithi == 2
                        and next_month == target_month_name
                    ):
                        
                        started = True

                        navratri_days.append({
                            "day_number": 1,
                            "date": d.strftime("%Y-%m-%d"),
                            "tithi": 1,
                            "label": "Kalash Sthapana"
                        })

        else:
            if 1 <= tithi_sunrise <= 10:

                if str(d) not in [x['date'] for x in navratri_days]:
                    day_num = len(navratri_days) + 1

                    
                    navratri_days.append({
                        "day_number": day_num,
                        "date": d.strftime("%Y-%m-%d"),
                        "tithi": tithi_sunrise,
                        "label": f"Navratri Day {day_num}"
                    })

            if len(navratri_days) >= 9 or tithi_sunrise >= 10:
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

def build_full_navratri(year, lat, lon, navratri_type="chaitra"):

    base = detect_navratri(year, lat, lon, navratri_type)

    if "error" in base:
        return base

    days = base["days"]

    # ---------------------------------
    # Attach Mata Names + Panchang Data
    # ---------------------------------
    enriched_days = []

    for d in days:
        date_obj = datetime.strptime(d["date"], "%Y-%m-%d").date()

        panchang = calculate_panchang(date_obj, lat, lon, "en")

        d["mata_name"] = NAVRATRI_DAY_MAP.get(d["day_number"])
        d["sunrise"] = panchang["sunrise"]
        d["sunset"] = panchang["sunset"]
        d["abhijit_muhurta"] = panchang["abhijit_muhurta"]
        d["brahma_muhurta"] = panchang["brahma_muhurta"]
        d["rahu_kaal"] = panchang["rahu_kaal"]
        d["tithi_window"] = panchang["tithi"]
        d["kshaya"] = panchang["tithi_special"]["kshaya"]
        d["vriddhi"] = panchang["tithi_special"]["vriddhi"]

        enriched_days.append(d)

    # ---------------------------------
    # Kalash Sthapana = Day 1 Panchang
    # ---------------------------------
    kalash_day = enriched_days[0]

    kalash_muhurta = {
        "date": kalash_day["date"],
        "sunrise": kalash_day["sunrise"],
        "abhijit_muhurta": kalash_day["abhijit_muhurta"],
        "brahma_muhurta": kalash_day["brahma_muhurta"],
        "rahu_kaal": kalash_day["rahu_kaal"],
    }

    # ---------------------------------
    # Sandhi Puja (Ashtami → Navami Boundary)
    # ---------------------------------
    sandhi_puja = None
    ashtami = next((x for x in enriched_days if x["day_number"] == 8), None)

    if ashtami:
        transitions = ashtami["tithi_window"].get("start_ist")
        sandhi_puja = {
            "date": ashtami["date"],
            "note": "Use exact Navami transition from tithi_special.transition_times_ist if needed"
        }

    # ---------------------------------
    # Vijayadashami (Day 9 Panchang Based Aparahna)
    # ---------------------------------
    dashami = enriched_days[-1]

    dashami_date_obj = datetime.strptime(dashami["date"], "%Y-%m-%d").date()
    dashami_panchang = calculate_panchang(dashami_date_obj, lat, lon, "en")

    sunrise = datetime.strptime(
        dashami["date"] + " " + dashami_panchang["sunrise"],
        "%Y-%m-%d %H:%M"
    )
    sunset = datetime.strptime(
        dashami["date"] + " " + dashami_panchang["sunset"],
        "%Y-%m-%d %H:%M"
    )

    day_duration = sunset - sunrise
    one_part = day_duration / 5

    aparahna_start = sunrise + one_part * 2
    aparahna_end = sunrise + one_part * 3

    vijayadashami = {
        "date": dashami["date"],
        "aparahna_start": aparahna_start.strftime("%H:%M"),
        "aparahna_end": aparahna_end.strftime("%H:%M")
    }

    # ---------------------------------
    # Final Response
    # ---------------------------------
    return {
        "type": navratri_type,
        "year": year,
        "start_date": enriched_days[0]["date"],
        "end_date": enriched_days[-1]["date"],
        "total_days": len(enriched_days),
        "kalash_sthapana": kalash_muhurta,
        "sandhi_puja": sandhi_puja,
        "vijayadashami": vijayadashami,
        "days": enriched_days
    }