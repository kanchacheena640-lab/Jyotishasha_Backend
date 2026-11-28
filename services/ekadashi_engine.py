import re
from datetime import datetime, timedelta
from functools import lru_cache

from services.panchang_engine import _tithi_number_at, _tithi_start_end_ist
from services.sun_calc import calculate_sunrise_sunset
from services.lunar_month_engine import get_lunar_month

# --- Configuration & Mapping ---
HINDU_MONTHS = [
    "Chaitra", "Vaishakha", "Jyeshtha", "Ashadha", "Shravana", "Bhadrapada", 
    "Ashwin", "Kartik", "Margashirsha", "Pausha", "Magha", "Phalguna"
]

EKADASHI_MAP = {
    ("Chaitra", "Shukla"): ("Kamada", "कामदा"),
    ("Chaitra", "Krishna"): ("Papmochini", "पापमोचिनी"),
    ("Vaishakha", "Shukla"): ("Mohini", "मोहिनी"),
    ("Vaishakha", "Krishna"): ("Varuthini", "वरूथिनी"),
    ("Jyeshtha", "Shukla"): ("Nirjala", "निर्जला"),
    ("Jyeshtha", "Krishna"): ("Apara", "अपरा"),
    ("Ashadha", "Shukla"): ("Devshayani", "देवशयनी"),
    ("Ashadha", "Krishna"): ("Yogini", "योगिनी"),
    ("Shravana", "Shukla"): ("Putrada (Shravana)", "पुत्रदा"),
    ("Shravana", "Krishna"): ("Kamika", "कामिका"),
    ("Bhadrapada", "Shukla"): ("Parsva", "परिवर्तिनी"),
    ("Bhadrapada", "Krishna"): ("Aja", "अजा"),
    ("Ashwin", "Shukla"): ("Papankusha", "पापांकुशा"),
    ("Ashwin", "Krishna"): ("Indira", "इन्दिरा"),
    ("Kartik", "Shukla"): ("Devutthana", "देवोत्थान"),
    ("Kartik", "Krishna"): ("Rama", "रमा"),
    ("Margashirsha", "Shukla"): ("Mokshada", "मोक्षदा"),
    ("Margashirsha", "Krishna"): ("Utpanna", "उत्पन्ना"),
    ("Pausha", "Shukla"): ("Putrada (Pausha)", "पुत्रदा"),
    ("Pausha", "Krishna"): ("Saphala", "सफला"),
    ("Magha", "Shukla"): ("Jaya", "जया"),
    ("Magha", "Krishna"): ("Shattila", "षटतिला"),
    ("Phalguna", "Shukla"): ("Amalaki", "आमलकी"),
    ("Phalguna", "Krishna"): ("Vijaya", "विजया"),
}

def get_ekadashi_name(engine_month, tithi_number, is_adhik):
    normalized_tithi = ((tithi_number - 1) % 30) + 1
    is_shukla = 1 <= normalized_tithi <= 15
    paksha_key = "Shukla" if is_shukla else "Krishna"

    if is_adhik:
        return ("Padmini Ekadashi", "पद्मिनी एकादशी") if is_shukla else ("Parama Ekadashi", "परमा एकादशी")

    # get_lunar_month() returns the Purnimanta month (Drik Panchang, North India)
    # directly. The former +1 display offset compensated a one-month lag in the
    # shared engine and was removed together with that fix.
    return EKADASHI_MAP.get((engine_month, paksha_key), ("Ekadashi", "एकादशी"))


# --- Helpers ---
def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")

EKADASHI_TITHIS = (11, 26)
DWADASHI_TITHIS = (12, 27)


@lru_cache(maxsize=32)
def _sun_times(day, lat, lon):
    sunrise, sunset = calculate_sunrise_sunset(day, lat, lon)
    if sunrise is None or sunset is None:
        raise ValueError(f"No solar transit for {day} at {lat}, {lon}")
    # The shared tithi helpers take naive IST datetimes.
    return sunrise.replace(tzinfo=None), sunset.replace(tzinfo=None)


def _fmt_dt(dt):
    return dt.strftime("%Y-%m-%d %H:%M")


def _after_transition(boundary):
    # The shared transition search resolves to within one second.
    return boundary + timedelta(seconds=2)


def _ekadashi_interval(vrat_date, lat, lon):
    sunrise, _ = _sun_times(vrat_date, lat, lon)
    start, end, number = _tithi_start_end_ist(sunrise)
    if number in (10, 25):
        start, end, number = _tithi_start_end_ist(_after_transition(end))
    elif number in DWADASHI_TITHIS:
        start, end, number = _tithi_start_end_ist(start - timedelta(seconds=2))
    if number not in EKADASHI_TITHIS:
        raise ValueError(f"No Ekadashi interval adjacent to sunrise on {vrat_date}")
    return start, end, number


def _parana_from_interval(vrat_date, ekadashi_end, lat, lon):
    parana_day = vrat_date + timedelta(days=1)
    sunrise, sunset = _sun_times(parana_day, lat, lon)
    dwadashi_start, dwadashi_end, number = _tithi_start_end_ist(
        _after_transition(ekadashi_end)
    )
    if number not in DWADASHI_TITHIS:
        raise ValueError(f"Expected Dwadashi after {ekadashi_end}")

    hari_vasara_end = dwadashi_start + (dwadashi_end - dwadashi_start) / 4
    daylight_part = (sunset - sunrise) / 5
    morning_end = sunrise + daylight_part
    afternoon_start = sunrise + 3 * daylight_part
    afternoon_end = sunrise + 4 * daylight_part
    earliest = max(sunrise, hari_vasara_end)

    # Regional Smarta convention: prefer Pratahkal, avoid Madhyahna when
    # possible, and break the fast after sunrise if Dwadashi ended overnight.
    if dwadashi_end <= sunrise:
        start, end = sunrise, morning_end
        rule = "after_dwadashi"
    elif earliest < min(morning_end, dwadashi_end):
        start, end = earliest, min(morning_end, dwadashi_end)
        rule = "pratahkal"
    elif max(earliest, afternoon_start) < min(afternoon_end, dwadashi_end):
        start, end = max(earliest, afternoon_start), min(afternoon_end, dwadashi_end)
        rule = "aparahna"
    else:
        # Dwadashi can expire before Aparahna. Use the available time
        # after Hari Vasara and within Dwadashi and local daylight.
        start, end = earliest, min(dwadashi_end, sunset)
        rule = "available_dwadashi"

    has_window = start < end and _fmt_dt(start) != _fmt_dt(end)
    return {
        "parana_date": parana_day.isoformat(),
        "start": _fmt_dt(start) if has_window else None,
        "end": _fmt_dt(end) if has_window else None,
        "hari_vasara_end": _fmt_dt(hari_vasara_end),
        "dwadashi_end": _fmt_dt(dwadashi_end),
        "rule": rule if has_window else "unavailable",
    }


def calculate_parana_window(vrat_date_obj, lat, lon):
    if isinstance(vrat_date_obj, datetime):
        vrat_date_obj = vrat_date_obj.date()
    _, ekadashi_end, _ = _ekadashi_interval(vrat_date_obj, lat, lon)
    return _parana_from_interval(vrat_date_obj, ekadashi_end, lat, lon)


def determine_ekadashi_observance(date_obj, lat, lon):
    sunrise, _ = _sun_times(date_obj, lat, lon)
    next_day = date_obj + timedelta(days=1)
    next_sunrise, _ = _sun_times(next_day, lat, lon)
    at_sunrise = _tithi_number_at(sunrise)
    at_next_sunrise = _tithi_number_at(next_sunrise)

    if at_sunrise in (10, 25):
        if at_next_sunrise == at_sunrise + 2:
            # Ekadashi is completely between consecutive sunrises.
            return "Gauna/Vaishnava", date_obj
        if at_next_sunrise == at_sunrise + 1:
            following_sunrise, _ = _sun_times(next_day + timedelta(days=1), lat, lon)
            if _tithi_number_at(following_sunrise) == at_sunrise + 3:
                return "Gauna/Vaishnava", date_obj

    if at_sunrise in EKADASHI_TITHIS:
        if at_next_sunrise == at_sunrise + 2:
            previous_sunrise, _ = _sun_times(date_obj - timedelta(days=1), lat, lon)
            if _tithi_number_at(previous_sunrise) == at_sunrise - 1:
                return None, None  # Already included as the previous day's alternate.
            return "Regular", date_obj

        arunodaya = sunrise - timedelta(minutes=96)
        if _tithi_number_at(arunodaya) == at_sunrise - 1:
            if at_next_sunrise == at_sunrise:
                return "Unmilini Mahadwadashi", next_day
            if at_next_sunrise == at_sunrise + 1:
                return "Vaishnava", date_obj

        if at_next_sunrise == at_sunrise:
            return "Unmilini Mahadwadashi", next_day
        if at_next_sunrise == at_sunrise + 1:
            following_sunrise, _ = _sun_times(next_day + timedelta(days=1), lat, lon)
            if _tithi_number_at(following_sunrise) == at_next_sunrise:
                return "Vaishnava", date_obj
        return "Regular", date_obj

    return None, None


def build_ekadashi_json(date_obj, lat, lon, language="en"):
    if isinstance(date_obj, datetime):
        date_obj = date_obj.date()
    for check_day in (date_obj - timedelta(days=1), date_obj):
        vrat_type, final_date = determine_ekadashi_observance(check_day, lat, lon)
        if final_date == date_obj:
            break
    else:
        return None

    start, end, number = _ekadashi_interval(date_obj, lat, lon)
    sunrise, _ = _sun_times(date_obj, lat, lon)
    # Keep the established month/slug mapping anchored to sunrise when
    # Ekadashi is present. For a skipped sunrise, query inside the tithi.
    month_reference = sunrise if start <= sunrise < end else _after_transition(start)
    month_data = get_lunar_month(month_reference)
    month = month_data["name"]
    is_adhik = month_data["is_adhik"]
    base_name, name_hi = get_ekadashi_name(month, number, is_adhik)
    name_en = base_name
    if not is_adhik and vrat_type == "Unmilini Mahadwadashi":
        name_en = f"{vrat_type.replace('/', ', ')}, {base_name}"

    result = {
        "type": "ekadashi",
        "name_en": name_en,
        "name_hi": name_hi,
        "slug": slugify(base_name),
        "vrat_date": date_obj.isoformat(),
        "tithi": {
            "start": _fmt_dt(start),
            "end": _fmt_dt(end),
            "paksha": "Shukla" if number == 11 else "Krishna",
            "month": month,
            "is_adhik": is_adhik,
        },
        "parana": _parana_from_interval(date_obj, end, lat, lon),
    }
    if vrat_type in ("Gauna/Vaishnava", "Vaishnava"):
        alternate_date = date_obj + timedelta(days=1)
        result["alternate_observances"] = [{
            "tradition": vrat_type,
            "vrat_date": alternate_date.isoformat(),
            "parana": _parana_from_interval(alternate_date, end, lat, lon),
        }]
    return result


def generate_year(year: int, lat: float, lon: float, language: str = "en"):
    current = datetime(year, 1, 1).date()
    end_date = datetime(year, 12, 31).date()
    rows = []
    while current <= end_date:
        observance = build_ekadashi_json(current, lat, lon, language)
        if observance:
            rows.append(observance)
        current += timedelta(days=1)
    return {"year": year, "count": len(rows), "ekadashi_list": rows}
