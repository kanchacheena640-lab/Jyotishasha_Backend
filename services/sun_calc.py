# services/sun_calc.py
from datetime import date, datetime, timedelta

# Try suntime first
from suntime import Sun

# Fallback import (Astral)
from astral import LocationInfo
from astral.sun import sun


def calculate_sunrise_sunset(target_date, latitude, longitude):
    """
    Calculate sunrise and sunset for a given date and coordinates.
    - Tries suntime first (fast)
    - Falls back to astral if suntime fails
    Returns datetime objects in IST.
    """
    try:
        # --- 1️⃣ Ensure target_date is valid ---
        if isinstance(target_date, str):
            y, m, d = map(int, target_date.split('-'))
            target_date = date(y, m, d)
        elif isinstance(target_date, datetime):
            target_date = target_date.date()
        elif not isinstance(target_date, date):
            raise ValueError("Invalid date type")

        print(f">> DEBUG: date={target_date}, lat={latitude}, lon={longitude}, type={type(target_date)}")

        # --- 2️⃣ Try SUNTIME ---
        try:
            sun_obj = Sun(latitude, longitude)
            sunrise_utc = sun_obj.get_sunrise_time(target_date)
            sunset_utc  = sun_obj.get_sunset_time(target_date)

            if not sunrise_utc or not sunset_utc:
                raise ValueError("Suntime returned None")

            sunrise_ist = sunrise_utc + timedelta(hours=5, minutes=30)
            sunset_ist  = sunset_utc + timedelta(hours=5, minutes=30)

            print(">> Using SUNTIME result")
            return sunrise_ist, sunset_ist

        except Exception as e1:
            print("[WARN] Suntime failed:", e1)
            print(">> Falling back to Astral...")

            # --- 3️⃣ Fallback: Astral ---
            location = LocationInfo(latitude=latitude, longitude=longitude)
            s = sun(location.observer, date=target_date)

            sunrise_utc = s["sunrise"]
            sunset_utc  = s["sunset"]

            sunrise_ist = sunrise_utc + timedelta(hours=5, minutes=30)
            sunset_ist  = sunset_utc + timedelta(hours=5, minutes=30)

            print(">> Using ASTRAL result")
            return sunrise_ist, sunset_ist

    except Exception as e:
        print("[ERROR] Sunrise/sunset calculation failed:", e)
        return None, None
