# services/panchang_engine.py

from datetime import datetime, timedelta
import swisseph as swe
from services.sun_calc import calculate_sunrise_sunset  # ✅ Imported here

# --- Constants ---
NAKSHATRAS = [
    "Ashwini","Bharani","Krittika","Rohini","Mrigashira",
    "Ardra","Punarvasu","Pushya","Ashlesha","Magha",
    "Purva Phalguni","Uttara Phalguni","Hasta","Chitra",
    "Swati","Vishakha","Anuradha","Jyeshtha","Mula",
    "Purva Ashadha","Uttara Ashadha","Shravana","Dhanishta",
    "Shatabhisha","Purva Bhadrapada","Uttara Bhadrapada","Revati"
]

YOGAS = [
    "Vishkumbha","Preeti","Ayushman","Saubhagya","Shobhana",
    "Atiganda","Sukarma","Dhriti","Shoola","Ganda",
    "Vriddhi","Dhruva","Vyaghata","Harshana","Vajra",
    "Siddhi","Vyatipata","Variyan","Parigha","Shiva",
    "Siddha","Sadhya","Shubha","Shukla","Brahma",
    "Indra","Vaidhriti"
]

KARANS_REPEATING = ["Bava","Balava","Kaulava","Taitila","Garaja","Vanija","Vishti (Bhadra)"]
KARANS_FIXED = ["Shakuni","Chatushpada","Naga","Kimstughna"]

TITHI_NAMES = [
    "Pratipada","Dvitiya","Tritiya","Chaturthi","Panchami","Shashthi","Saptami","Ashtami",
    "Navami","Dashami","Ekadashi","Dvadashi","Trayodashi","Chaturdashi","Purnima",
    "Pratipada","Dvitiya","Tritiya","Chaturthi","Panchami","Shashthi","Saptami","Ashtami",
    "Navami","Dashami","Ekadashi","Dvadashi","Trayodashi","Chaturdashi","Amavasya"
]

HINDU_MONTHS = [
    "Chaitra", "Vaishakha", "Jyeshtha", "Ashadha",
    "Shravana", "Bhadrapada", "Ashwin", "Kartik",
    "Margashirsha", "Pausha", "Magha", "Phalguna"
]

RAHU_INDEX_OF_DAY = [2, 7, 5, 6, 4, 3, 1]  # Monday..Sunday

# --- Swiss Ephemeris setup ---
swe.set_sid_mode(swe.SIDM_LAHIRI)
FLAGS = swe.FLG_SIDEREAL | swe.FLG_SWIEPH

# --- Utility conversions ---
def _to_ut_julday(dt_ist):
    utc = dt_ist - timedelta(hours=5, minutes=30)
    return swe.julday(utc.year, utc.month, utc.day, utc.hour + utc.minute/60 + utc.second/3600)

def _sidereal_longitudes(dt_ist):
    jd_ut = _to_ut_julday(dt_ist)
    sun = swe.calc_ut(jd_ut, swe.SUN, FLAGS)[0][0] % 360
    moon = swe.calc_ut(jd_ut, swe.MOON, FLAGS)[0][0] % 360
    return sun, moon

# --- Panchang limbs ---
def _tithi_from_longitudes(sun, moon):
    diff = (moon - sun) % 360
    num = int(diff // 12) + 1
    paksha = "Shukla" if num <= 15 else "Krishna"
    return num, paksha, TITHI_NAMES[num - 1]

def _nakshatra_from_moon(moon):
    span = 360.0 / 27.0
    idx = int(moon // span)
    pada = int(((moon % span) // (span / 4.0)) + 1)
    return NAKSHATRAS[idx], idx + 1, pada

def _yoga_from_lons(sun, moon):
    total = (sun + moon) % 360
    idx = int(total // (360 / 27))
    return YOGAS[idx], idx + 1

def _karan_from_tithi(tithi_num):
    if tithi_num < 1 or tithi_num > 30:
        return "Unknown", -1
    slot = (tithi_num * 2) - 1
    if slot < 57:
        return KARANS_REPEATING[slot % 7], slot
    return KARANS_FIXED[min(slot - 57, 3)], slot

def _approx_hindu_month(date):
    """Approximate lunar month name based on Sun's sidereal longitude (for accuracy use solar transition)."""
    jd_ut = swe.julday(date.year, date.month, date.day, 12)
    sun_long = swe.calc_ut(jd_ut, swe.SUN, FLAGS)[0][0] % 360
    # Each month covers 30 degrees of Sun's motion starting from Mesha (Aries)
    idx = int((sun_long // 30) % 12)
    return HINDU_MONTHS[idx]

# ✅ --- Use imported sunrise/sunset instead of formula ---
def _rahu_kaal(date, sunrise, sunset):
    day_len = (sunset - sunrise).total_seconds()
    slot = day_len / 8.0
    idx = RAHU_INDEX_OF_DAY[date.weekday()]
    start = sunrise + timedelta(seconds=slot * idx)
    return start, start + timedelta(seconds=slot)

def _abhijit(sunrise, sunset):
    mid = sunrise + (sunset - sunrise) / 2
    return mid - timedelta(minutes=24), mid + timedelta(minutes=24)

# --- Tithi timing utilities ---
def _tithi_number_at(dt_ist):
    s, m = _sidereal_longitudes(dt_ist)
    return _tithi_from_longitudes(s, m)[0]

def _scan_for_change(t0, t1, step_min=30):
    base = _tithi_number_at(t0)
    step = timedelta(minutes=step_min)
    t = t0 + step
    while t <= t1:
        if _tithi_number_at(t) != base:
            return t - step, t
        t += step
    return None

def _binary_change(t0, t1):
    base = _tithi_number_at(t0)
    for _ in range(24):
        mid = t0 + (t1 - t0) / 2
        if _tithi_number_at(mid) == base:
            t0 = mid
        else:
            t1 = mid
    return t1

def _tithi_start_end_ist(date):
    d0 = datetime(date.year, date.month, date.day, 0, 0)
    d12 = datetime(date.year, date.month, date.day, 12, 0)
    d23 = datetime(date.year, date.month, date.day, 23, 59)
    prev = _scan_for_change(d0, d12)
    nxt = _scan_for_change(d12, d23)
    t_start = _binary_change(*prev) if prev else d0 - timedelta(seconds=1)
    t_end = _binary_change(*nxt) if nxt else d23 + timedelta(seconds=1)
    return t_start, t_end, _tithi_number_at(d12)

# --- Final Public API ---
def calculate_panchang(date, lat, lon):
    ref = datetime(date.year, date.month, date.day, 12)
    sun, moon = _sidereal_longitudes(ref)
    t_num, paksha, t_name = _tithi_from_longitudes(sun, moon)
    n_name, n_idx, n_pada = _nakshatra_from_moon(moon)
    y_name, y_idx = _yoga_from_lons(sun, moon)
    k_name, k_slot = _karan_from_tithi(t_num)

    # ✅ Sunrise/Sunset from external function
    sunrise, sunset = calculate_sunrise_sunset(date, lat, lon)
    rahu_s, rahu_e = _rahu_kaal(date, sunrise, sunset)
    abhi_s, abhi_e = _abhijit(sunrise, sunset)
    t_start, t_end, _ = _tithi_start_end_ist(date)

    # ✅ Panchak detection logic
    PANCHAK_NAKSHATRAS = ["Dhanishta", "Shatabhisha", "Purva Bhadrapada", "Uttara Bhadrapada", "Revati"]
    is_panchak = n_name in PANCHAK_NAKSHATRAS
    
    month_name = _approx_hindu_month(date)

    return {
        "date": date.strftime("%Y-%m-%d"),
        "weekday": date.strftime("%A"),
        "month_name": month_name,
        
        "tithi": {
            "number": t_num,
            "name": t_name,
            "paksha": paksha,
            "start_ist": t_start.strftime("%Y-%m-%d %H:%M"),
            "end_ist": t_end.strftime("%Y-%m-%d %H:%M")
        },
        "nakshatra": {"name": n_name, "index": n_idx, "pada": n_pada},
        "yoga": {"name": y_name, "index": y_idx},
        "karan": {"name": k_name, "slot": k_slot},
        "panchak": {
            "active": is_panchak,
            "nakshatra": n_name if is_panchak else None,
            "message": "⚠️ Panchak Kaal in effect – avoid construction, travel, and cremation."
            if is_panchak else "✅ No Panchak today."
        },
        "sunrise": sunrise.strftime("%H:%M"),
        "sunset": sunset.strftime("%H:%M"),
        "rahu_kaal": {"start": rahu_s.strftime("%H:%M"), "end": rahu_e.strftime("%H:%M")},
        "abhijit_muhurta": {"start": abhi_s.strftime("%H:%M"), "end": abhi_e.strftime("%H:%M")},
        "ayanamsa": "Lahiri"
        
    }


def today_and_tomorrow(lat, lon):
    today = datetime.now().date()
    return {
        "selected_date": calculate_panchang(today, lat, lon),
        "next_date": calculate_panchang(today + timedelta(days=1), lat, lon)
    }

def panchang_range(start_date, end_date, lat, lon):
    out = []
    d = start_date
    while d <= end_date:
        out.append(calculate_panchang(d, lat, lon))
        d += timedelta(days=1)
    return out
