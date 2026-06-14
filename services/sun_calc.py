# services/sun_calc.py

from datetime import date, datetime
from astral import Observer
from astral.sun import sunrise, sunset
from zoneinfo import ZoneInfo


def calculate_sunrise_sunset(
    target_date,
    latitude,
    longitude
):
    """
    Calculate sunrise and sunset using Astral.
    Returns IST datetime objects.
    """

    try:

        # Normalize date
        if isinstance(target_date, str):
            y, m, d = map(
                int,
                target_date.split("-")
            )

            target_date = datetime(y, m, d)

        elif isinstance(target_date, date):
            target_date = datetime(
                target_date.year,
                target_date.month,
                target_date.day
            )

        elif not isinstance(
            target_date,
            datetime
        ):
            raise ValueError(
                "Invalid date type"
            )

        observer = Observer(
            latitude=latitude,
            longitude=longitude
        )

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

        return (
            sunrise_ist,
            sunset_ist
        )

    except Exception as e:
        print(
            "[ERROR] Sunrise/sunset calculation failed:",
            e
        )

        return None, None