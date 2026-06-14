# services/sun_calc.py
from datetime import date, datetime, timedelta

# Try suntime first
#from suntime import Sun

# Fallback import (Astral)
from astral import Observer
from astral.sun import sunrise, sunset
from zoneinfo import ZoneInfo


def calculate_sunrise_sunset(target_date, latitude, longitude):
    """
    Calculate sunrise and sunset using Astral only.
    """

    try:
        # Normalize target_date → datetime
        if isinstance(target_date, str):
            y, m, d = map(int, target_date.split('-'))
            target_date = datetime(y, m, d)

        elif isinstance(target_date, date):
            target_date = datetime(
                target_date.year,
                target_date.month,
                target_date.day
            )

        elif isinstance(target_date, datetime):
            pass

        else:
            raise ValueError("Invalid date type")

        print(
            f">> DEBUG FIXED: date={target_date}, "
            f"lat={latitude}, lon={longitude}, "
            f"type={type(target_date)}"
        )

        # Astral Only
        observer = Observer(
            latitude=latitude,
            longitude=longitude
        )

        print("DATE TO CHECK:", target_date.date())
        print("LAT:", latitude)
        print("LON:", longitude)

        sunrise_utc = sunrise(
            observer,
            date=target_date.date()
        )

        sunset_utc = sunset(
            observer,
            date=target_date.date()
        )

        sunrise_ist = sunrise_utc.astimezone(
            ZoneInfo("Asia/Kolkata")
        )

        sunset_ist = sunset_utc.astimezone(
            ZoneInfo("Asia/Kolkata")
        )

        print("================================")
        print("USING ASTRAL ONLY")
        print("TARGET DATE =", target_date)
        print("RAW SUNRISE =", sunrise_utc)
        print("RAW SUNSET  =", sunset_utc)

        print("SUNRISE TZ =", sunrise_utc.tzinfo)
        print("SUNSET TZ  =", sunset_utc.tzinfo)

        print("SUNRISE IST =", sunrise_ist)
        print("SUNSET IST  =", sunset_ist)
        print("================================")

        return sunrise_ist, sunset_ist

    except Exception as e:
            print(
                "[ERROR] Sunrise/sunset calculation failed:",
                repr(e)
            )
            raise