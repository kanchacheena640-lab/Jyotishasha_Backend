from datetime import datetime, timedelta
import swisseph as swe
from services.panchang_engine import _to_ut_julday, calculate_panchang

FLAGS = swe.FLG_SIDEREAL | swe.FLG_SWIEPH

RASHI_NAMES_EN = [
    "Aries", "Taurus", "Gemini", "Cancer",
    "Leo", "Virgo", "Libra", "Scorpio",
    "Sagittarius", "Capricorn", "Aquarius", "Pisces"
]

RASHI_NAMES_HI = [
    "मेष", "वृषभ", "मिथुन", "कर्क",
    "सिंह", "कन्या", "तुला", "वृश्चिक",
    "धनु", "मकर", "कुंभ", "मीन"
]


# ---------------------------------------------------
# SUN CALCULATIONS
# ---------------------------------------------------

def _get_sun_longitude(dt_ist):
    jd_ut = _to_ut_julday(dt_ist)
    return swe.calc_ut(jd_ut, swe.SUN, FLAGS)[0][0] % 360


def _get_sun_sign_index(dt_ist):
    return int(_get_sun_longitude(dt_ist) // 30)


# ---------------------------------------------------
# EXACT SANKRANTI TIME (Binary Search)
# ---------------------------------------------------

def _find_exact_ingress(date):
    start_dt = datetime.combine(date, datetime.min.time())
    end_dt = start_dt + timedelta(days=1)

    start_sign = _get_sun_sign_index(start_dt)
    end_sign = _get_sun_sign_index(end_dt)

    if start_sign == end_sign:
        return None

    low = start_dt
    high = end_dt

    while (high - low).total_seconds() > 1:
        mid = low + (high - low) / 2
        if _get_sun_sign_index(mid) == start_sign:
            low = mid
        else:
            high = mid

    return high


# ---------------------------------------------------
# PUNYA KAAL
# ---------------------------------------------------

def _calculate_punya_kaal(ingress_dt, lat, lon):
    date = ingress_dt.date()
    panchang = calculate_panchang(date, lat, lon, "en")

    sunset = panchang.get("sunset")
    sunrise = panchang.get("sunrise")

    sunset_dt = datetime.strptime(
        f"{date} {sunset}",
        "%Y-%m-%d %H:%M"
    )

    sunrise_dt = datetime.strptime(
        f"{date} {sunrise}",
        "%Y-%m-%d %H:%M"
    )

    # If ingress before sunset → same day punya
    if ingress_dt <= sunset_dt:
        punya_start = ingress_dt
        punya_end = sunset_dt
    else:
        # Next day sunrise based punya
        next_date = date + timedelta(days=1)
        next_panchang = calculate_panchang(next_date, lat, lon, "en")

        next_sunrise = datetime.strptime(
            f"{next_date} {next_panchang.get('sunrise')}",
            "%Y-%m-%d %H:%M"
        )

        punya_start = next_sunrise
        punya_end = next_sunrise + timedelta(minutes=96)

    return punya_start, punya_end


def _calculate_maha_punya(punya_start):
    return punya_start, punya_start + timedelta(minutes=40)


# ---------------------------------------------------
# MAIN PUBLIC FUNCTION
# ---------------------------------------------------

def get_sankranti_details(date, lat, lon, language="en"):
    """
    Returns Sankranti details for given date.
    If no ingress that day → None
    """

    ingress_dt = _find_exact_ingress(date)

    if not ingress_dt:
        return None

    sign_index = _get_sun_sign_index(ingress_dt)

    if language == "hi":
        sign_name = RASHI_NAMES_HI[sign_index]
    else:
        sign_name = RASHI_NAMES_EN[sign_index]

    punya_start, punya_end = _calculate_punya_kaal(
        ingress_dt, lat, lon
    )

    maha_start, maha_end = _calculate_maha_punya(punya_start)

    return {
        "type": "sankranti",
        "date": date.strftime("%Y-%m-%d"),
        "sun_enters": sign_name,
        "ingress_time": ingress_dt.strftime("%H:%M"),
        "punya_kaal_start": punya_start.strftime("%H:%M"),
        "punya_kaal_end": punya_end.strftime("%H:%M"),
        "maha_punya_start": maha_start.strftime("%H:%M"),
        "maha_punya_end": maha_end.strftime("%H:%M"),
    }

# ==========================================================
# SANKRANTI DETECTOR
# ==========================================================

def find_next_sankranti(start_date, lat, lon, language="en", days_ahead=40):

    for i in range(0, days_ahead + 1):
        check_date = start_date + timedelta(days=i)

        sankranti = get_sankranti_details(
            check_date, lat, lon, language
        )

        if sankranti:
            return sankranti

    return None