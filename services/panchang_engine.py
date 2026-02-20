# services/panchang_engine.py

from datetime import datetime, timedelta
import swisseph as swe
from services.sun_calc import calculate_sunrise_sunset  
from services.astro_core import _tithi_number_at
from services.astro_core import sidereal_longitudes


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

# --- Hindi mappings (for language == "hi") ---
WEEKDAYS_HI = {
    "Monday": "सोमवार",
    "Tuesday": "मंगलवार",
    "Wednesday": "बुधवार",
    "Thursday": "गुरुवार",
    "Friday": "शुक्रवार",
    "Saturday": "शनिवार",
    "Sunday": "रविवार",
}

HINDU_MONTHS_HI = {
    "Chaitra": "चैत्र",
    "Vaishakha": "वैशाख",
    "Jyeshtha": "ज्येष्ठ",
    "Ashadha": "आषाढ़",
    "Shravana": "श्रावण",
    "Bhadrapada": "भाद्रपद",
    "Ashwin": "आश्विन",
    "Kartik": "कार्तिक",
    "Margashirsha": "मार्गशीर्ष",
    "Pausha": "पौष",
    "Magha": "माघ",
    "Phalguna": "फाल्गुन",
}

PAKSHA_HI = {
    "Shukla": "शुक्ल पक्ष",
    "Krishna": "कृष्ण पक्ष",
}

TITHI_NAMES_HI = [
    "प्रतिपदा","द्वितीया","तृतीया","चतुर्थी","पंचमी","षष्ठी","सप्तमी","अष्टमी",
    "नवमी","दशमी","एकादशी","द्वादशी","त्रयोदशी","चतुर्दशी","पूर्णिमा",
    "प्रतिपदा","द्वितीया","तृतीया","चतुर्थी","पंचमी","षष्ठी","सप्तमी","अष्टमी",
    "नवमी","दशमी","एकादशी","द्वादशी","त्रयोदशी","चतुर्दशी","अमावस्या",
]

NAKSHATRAS_HI = {
    "Ashwini": "अश्विनी",
    "Bharani": "भरणी",
    "Krittika": "कृत्तिका",
    "Rohini": "रोहिणी",
    "Mrigashira": "मृगशिरा",
    "Ardra": "आर्द्रा",
    "Punarvasu": "पुनर्वसु",
    "Pushya": "पुष्य",
    "Ashlesha": "आश्लेषा",
    "Magha": "मघा",
    "Purva Phalguni": "पूर्व फाल्गुनी",
    "Uttara Phalguni": "उत्तर फाल्गुनी",
    "Hasta": "हस्त",
    "Chitra": "चित्रा",
    "Swati": "स्वाती",
    "Vishakha": "विशाखा",
    "Anuradha": "अनुराधा",
    "Jyeshtha": "ज्येष्ठा",
    "Mula": "मूल",
    "Purva Ashadha": "पूर्वाषाढ़ा",
    "Uttara Ashadha": "उत्तराषाढ़ा",
    "Shravana": "श्रवण",
    "Dhanishta": "धनिष्ठा",
    "Shatabhisha": "शतभिषा",
    "Purva Bhadrapada": "पूर्व भाद्रपद",
    "Uttara Bhadrapada": "उत्तर भाद्रपद",
    "Revati": "रेवती",
}

YOGAS_HI = {
    "Vishkumbha": "विष्कंभ",
    "Preeti": "प्रीति",
    "Ayushman": "आयुष्मान",
    "Saubhagya": "सौभाग्य",
    "Shobhana": "शोभन",
    "Atiganda": "अतिगंड",
    "Sukarma": "सुकर्मा",
    "Dhriti": "धृति",
    "Shoola": "शूल",
    "Ganda": "गंड",
    "Vriddhi": "वृद्धि",
    "Dhruva": "ध्रुव",
    "Vyaghata": "व्याघात",
    "Harshana": "हर्षण",
    "Vajra": "वज्र",
    "Siddhi": "सिद्धि",
    "Vyatipata": "व्यतीपात",
    "Variyan": "वरियन",
    "Parigha": "परिघ",
    "Shiva": "शिव",
    "Siddha": "सिद्ध",
    "Sadhya": "साध्य",
    "Shubha": "शुभ",
    "Shukla": "शुक्ल",
    "Brahma": "ब्रह्म",
    "Indra": "इन्द्र",
    "Vaidhriti": "वैधृति",
}

KARAN_HI = {
    "Bava": "बव",
    "Balava": "बालव",
    "Kaulava": "कौलव",
    "Taitila": "तैतिल",
    "Garaja": "गरज",
    "Vanija": "वणिज",
    "Vishti (Bhadra)": "विष्टि (भद्रा)",
    "Shakuni": "शकुनी",
    "Chatushpada": "चतुष्पद",
    "Naga": "नाग",
    "Kimstughna": "किंस्तुघ्न",
    "Unknown": "अज्ञात",
}

PANCHAK_MSG_HI = {
    True: "⚠️ पंचक काल सक्रिय – निर्माण, यात्रा और अंतिम संस्कार से बचें।",
    False: "✅ आज पंचक नहीं है।",
}

# --- Chaughadiya constants ---
CHAUGHADIYA_DAY = {
    "Sunday":    ["Udveg", "Chal", "Labh", "Amrit", "Kaal", "Shubh", "Rog", "Udveg"],
    "Monday":    ["Amrit", "Kaal", "Shubh", "Rog", "Udveg", "Chal", "Labh", "Amrit"],
    "Tuesday":   ["Rog", "Udveg", "Chal", "Labh", "Amrit", "Kaal", "Shubh", "Rog"],
    "Wednesday": ["Labh", "Amrit", "Kaal", "Shubh", "Rog", "Udveg", "Chal", "Labh"],
    "Thursday":  ["Shubh", "Rog", "Udveg", "Chal", "Labh", "Amrit", "Kaal", "Shubh"],
    "Friday":    ["Chal", "Labh", "Amrit", "Kaal", "Shubh", "Rog", "Udveg", "Chal"],
    "Saturday":  ["Kaal", "Shubh", "Rog", "Udveg", "Chal", "Labh", "Amrit", "Kaal"],
}
SHUBH_CHAUGHADIYA = {"Amrit", "Shubh", "Labh"}

# --- Chaughadiya Hindi mapping ---
CHAUGHADIYA_HI = {
    "Amrit": "अमृत",
    "Shubh": "शुभ",
    "Labh": "लाभ",
    "Chal": "चल",
    "Rog": "रोग",
    "Kaal": "काल",
    "Udveg": "उद्वेग",
}
CHAUGHADIYA_NATURE_HI = {
    "shubh": "शुभ",
    "ashubh": "अशुभ",
}

# --- Swiss Ephemeris setup ---
swe.set_sid_mode(swe.SIDM_LAHIRI)
FLAGS = swe.FLG_SIDEREAL | swe.FLG_SWIEPH

# --- Utility conversions ---
def _to_ut_julday(dt_ist):
    utc = dt_ist - timedelta(hours=5, minutes=30)
    return swe.julday(
        utc.year,
        utc.month,
        utc.day,
        utc.hour + utc.minute / 60 + utc.second / 3600,
    )

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

def _approx_hindu_month(date_or_dt):
    if isinstance(date_or_dt, datetime):
        dt = date_or_dt
    else:
        dt = datetime(date_or_dt.year, date_or_dt.month, date_or_dt.day, 12)

    jd_ut = _to_ut_julday(dt)
    sun_long = swe.calc_ut(jd_ut, swe.SUN, FLAGS)[0][0] % 360
    idx = int((sun_long // 30) % 12)
    return HINDU_MONTHS[idx]

# -------------------------------
# DAY WINDOW NORMALIZER (KEEP THIS)
# -------------------------------
def _normalize_day_window(sunrise, sunset):
    if sunset <= sunrise:
        sunset = sunset + timedelta(days=1)
    return sunrise, sunset

# -------------------------------
# CHAUGHADIYA (KEEP IN MIDDLE; DO NOT MOVE BELOW USE)
# -------------------------------
def _divide_into_8(start, end):
    slot = (end - start) / 8
    return [(start + i * slot, start + (i + 1) * slot) for i in range(8)]

def _calculate_chaughadiya(date, sunrise, sunset, language="en"):
    sunrise, sunset = _normalize_day_window(sunrise, sunset)
    weekday = date.strftime("%A")

    # Day
    day_slots = _divide_into_8(sunrise, sunset)
    day_names = CHAUGHADIYA_DAY[weekday]

    # Night
    next_sunrise = sunrise + timedelta(days=1)
    night_slots = _divide_into_8(sunset, next_sunrise)
    night_names = day_names[1:] + day_names[:1]

    def pack(slots, names):
        out = []
        for (s, e), name in zip(slots, names):
            nature = "shubh" if name in SHUBH_CHAUGHADIYA else "ashubh"
            out.append({
                "name": name if language == "en" else CHAUGHADIYA_HI.get(name, name),
                "name_en": name,
                "nature": nature if language == "en" else CHAUGHADIYA_NATURE_HI[nature],
                "nature_en": nature,
                "start": s.strftime("%H:%M"),
                "end": e.strftime("%H:%M"),
            })
        return out

    return {
        "day": pack(day_slots, day_names),
        "night": pack(night_slots, night_names),
    }

# ✅ --- Use imported sunrise/sunset instead of formula ---
def _rahu_kaal(date, sunrise, sunset):
    sunrise, sunset = _normalize_day_window(sunrise, sunset)

    day_len = (sunset - sunrise).total_seconds()
    slot = day_len / 8.0
    idx = RAHU_INDEX_OF_DAY[sunrise.weekday()]

    start = sunrise + timedelta(seconds=slot * idx)
    return start, start + timedelta(seconds=slot)

def _abhijit(sunrise, sunset):
    sunrise, sunset = _normalize_day_window(sunrise, sunset)

    mid = sunrise + (sunset - sunrise) / 2
    return mid - timedelta(minutes=24), mid + timedelta(minutes=24)

def _brahma_muhurta(sunrise):
    """
    Brahma Muhurta:
    Starts 1h 36m before sunrise, lasts 48 minutes
    """
    start = sunrise - timedelta(minutes=96)
    end = start + timedelta(minutes=48)
    return start, end

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

def _karan_at(dt_ist):
    """
    Exact Karan at specific IST datetime.
    Used for festival-level precision (Holika Dahan etc).
    """
    sun, moon = sidereal_longitudes(dt_ist)
    diff = (moon - sun) % 360.0

    # 1..60 karan slots (each = 6 degrees)
    slot = int(diff // 6.0) + 1

    if slot == 1:
        return "Kimstughna", slot
    if 2 <= slot <= 56:
        return KARANS_REPEATING[(slot - 2) % 7], slot
    if slot == 57:
        return "Shakuni", slot
    if slot == 58:
        return "Chatushpada", slot
    if slot == 59:
        return "Naga", slot
    if slot == 60:
        return "Vishti (Bhadra)", slot

    return "Unknown", slot

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
def calculate_panchang(date, lat, lon, language="en", ref_dt_ist=None):
    language = (language or "en").lower()
    if language not in ("en", "hi"):
        language = "en"

    ref = ref_dt_ist or datetime(date.year, date.month, date.day, 12)
    sun, moon = sidereal_longitudes(ref)
    t_num, paksha, t_name = _tithi_from_longitudes(sun, moon)
    n_name, n_idx, n_pada = _nakshatra_from_moon(moon)
    y_name, y_idx = _yoga_from_lons(sun, moon)
    k_name, k_slot = _karan_from_tithi(t_num)

    # ✅ Sunrise/Sunset from external function
    sunrise, sunset = calculate_sunrise_sunset(date, lat, lon)

    # ✅ Chaughadiya derived from sunrise/sunset + weekday
    chaughadiya = _calculate_chaughadiya(date, sunrise, sunset, language)

    rahu_s, rahu_e = _rahu_kaal(date, sunrise, sunset)
    abhi_s, abhi_e = _abhijit(sunrise, sunset)
    brahma_s, brahma_e = _brahma_muhurta(sunrise)
    t_start, t_end, _ = _tithi_start_end_ist(date)

    PANCHAK_NAKSHATRAS = ["Dhanishta", "Shatabhisha", "Purva Bhadrapada", "Uttara Bhadrapada", "Revati"]
    is_panchak = n_name in PANCHAK_NAKSHATRAS

    month_name_en = _approx_hindu_month(ref)
    weekday_en = date.strftime("%A")

    weekday_val = WEEKDAYS_HI.get(weekday_en, weekday_en) if language == "hi" else weekday_en
    month_name_val = HINDU_MONTHS_HI.get(month_name_en, month_name_en) if language == "hi" else month_name_en
    tithi_name_val = t_name if language == "en" else TITHI_NAMES_HI[t_num - 1]
    paksha_val = paksha if language == "en" else PAKSHA_HI.get(paksha, paksha)
    nakshatra_name_val = n_name if language == "en" else NAKSHATRAS_HI.get(n_name, n_name)
    yoga_name_val = y_name if language == "en" else YOGAS_HI.get(y_name, y_name)
    karan_name_val = k_name if language == "en" else KARAN_HI.get(k_name, k_name)

    if language == "hi":
        panchak_message_val = PANCHAK_MSG_HI[is_panchak]
        panchak_nakshatra_val = NAKSHATRAS_HI.get(n_name, n_name) if is_panchak else None
    else:
        panchak_message_val = (
            "⚠️ Panchak Kaal in effect – avoid construction, travel, and cremation."
            if is_panchak else "✅ No Panchak today."
        )
        panchak_nakshatra_val = n_name if is_panchak else None

    return {
        "language": language,
        "date": date.strftime("%Y-%m-%d"),
        "weekday": weekday_val,
        "month_name": month_name_val,

        "tithi": {
            "number": t_num,
            "name": tithi_name_val,
            "paksha": paksha_val,
            "start_ist": t_start.strftime("%Y-%m-%d %H:%M"),
            "end_ist": t_end.strftime("%Y-%m-%d %H:%M"),
        },
        "nakshatra": {
            "name": nakshatra_name_val,
            "index": n_idx,
            "pada": n_pada,
        },
        "yoga": {"name": yoga_name_val, "index": y_idx},
        "karan": {"name": karan_name_val, "slot": k_slot},
        "panchak": {
            "active": is_panchak,
            "nakshatra": panchak_nakshatra_val,
            "message": panchak_message_val,
        },
        "sunrise": sunrise.strftime("%H:%M"),
        "sunset": sunset.strftime("%H:%M"),
        "rahu_kaal": {
            "start": rahu_s.strftime("%H:%M"),
            "end": rahu_e.strftime("%H:%M"),
        },
        "abhijit_muhurta": {
            "start": abhi_s.strftime("%H:%M"),
            "end": abhi_e.strftime("%H:%M"),
        },
        "ayanamsa": "Lahiri",

        # ✅ New non-breaking field
        "chaughadiya": chaughadiya,

        "brahma_muhurta": {
            "start": brahma_s.strftime("%H:%M"),
            "end": brahma_e.strftime("%H:%M"),
        },
    }

def today_and_tomorrow(lat, lon, language="en"):
    language = (language or "en").lower()
    if language not in ("en", "hi"):
        language = "en"

    today = datetime.now().date()
    return {
        "selected_date": calculate_panchang(today, lat, lon, language),
        "next_date": calculate_panchang(today + timedelta(days=1), lat, lon, language),
    }

def panchang_range(start_date, end_date, lat, lon, language="en"):
    language = (language or "en").lower()
    if language not in ("en", "hi"):
        language = "en"

    out = []
    d = start_date
    while d <= end_date:
        out.append(calculate_panchang(d, lat, lon, language))
        d += timedelta(days=1)
    return out
