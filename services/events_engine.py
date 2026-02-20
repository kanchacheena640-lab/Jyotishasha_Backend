# services/events_engine.py

import re
from datetime import datetime, timedelta
from services.panchang_engine import calculate_panchang, _tithi_number_at
from services.moon_calc import get_moon_rise_set
from services.lunar_month_engine import get_shivratri_type
from services.lunar_month_engine import get_lunar_month





# ==========================================================
# EKADASHI MASTER MAP (English Primary, Hindi Secondary)
# ==========================================================

EKADASHI_MAP = {
    # (Month, Paksha) : (English Name, Hindi Name)

    ("Chaitra", "Krishna"): ("Papmochini Ekadashi", "पापमोचिनी एकादशी"),
    ("Chaitra", "Shukla"): ("Kamada Ekadashi", "कामदा एकादशी"),

    ("Vaishakha", "Krishna"): ("Varuthini Ekadashi", "वरूथिनी एकादशी"),
    ("Vaishakha", "Shukla"): ("Mohini Ekadashi", "मोहिनी एकादशी"),

    ("Jyeshtha", "Krishna"): ("Apara Ekadashi", "अपरा एकादशी"),
    ("Jyeshtha", "Shukla"): ("Nirjala Ekadashi", "निर्जला एकादशी"),

    ("Ashadha", "Krishna"): ("Yogini Ekadashi", "योगिनी एकादशी"),
    ("Ashadha", "Shukla"): ("Devshayani Ekadashi", "देवशयनी एकादशी"),

    ("Shravana", "Krishna"): ("Kamika Ekadashi", "कामिका एकादशी"),
    ("Shravana", "Shukla"): ("Putrada Ekadashi (Shravana)", "पुत्रदा एकादशी"),

    ("Bhadrapada", "Krishna"): ("Aja Ekadashi", "अजा एकादशी"),
    ("Bhadrapada", "Shukla"): ("Parivartini Ekadashi", "परिवर्तिनी एकादशी"),

    ("Ashwin", "Krishna"): ("Indira Ekadashi", "इन्दिरा एकादशी"),
    ("Ashwin", "Shukla"): ("Papankusha Ekadashi", "पापांकुशा एकादशी"),

    ("Kartik", "Krishna"): ("Rama Ekadashi", "रमा एकादशी"),
    ("Kartik", "Shukla"): ("Devutthana Ekadashi", "देवोत्थान (देवउठनी) एकादशी"),

    ("Margashirsha", "Krishna"): ("Utpanna Ekadashi", "उत्पन्ना एकादशी"),
    ("Margashirsha", "Shukla"): ("Mokshada Ekadashi", "मोक्षदा एकादशी"),

    ("Pausha", "Krishna"): ("Saphala Ekadashi", "सफला एकादशी"),
    ("Pausha", "Shukla"): ("Putrada Ekadashi (Pausha)", "पुत्रदा एकादशी"),

    ("Magha", "Krishna"): ("Shattila Ekadashi", "षटतिला एकादशी"),
    ("Magha", "Shukla"): ("Jaya Ekadashi", "जया एकादशी"),

    ("Phalguna", "Krishna"): ("Vijaya Ekadashi", "विजया एकादशी"),
    ("Phalguna", "Shukla"): ("Amalaki Ekadashi", "आमलकी एकादशी"),
}

# ==========================================================
# Hindi Month → English Month Normalizer
# ==========================================================

HINDI_MONTH_TO_EN = {
    "चैत्र": "Chaitra",
    "वैशाख": "Vaishakha",
    "ज्येष्ठ": "Jyeshtha",
    "आषाढ़": "Ashadha",
    "श्रावण": "Shravana",
    "भाद्रपद": "Bhadrapada",
    "आश्विन": "Ashwin",
    "कार्तिक": "Kartik",
    "मार्गशीर्ष": "Margashirsha",
    "पौष": "Pausha",
    "माघ": "Magha",
    "फाल्गुन": "Phalguna",
}


# -----------------------------
# Helpers
# -----------------------------

EKADASHI_NUMBERS = (11, 26)
DWADASHI_NUMBERS = (12, 27)

def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")

def _parse_dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M")

def _fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")

def _fmt_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")

def _tithi_at(dt: datetime) -> int:
    return _tithi_number_at(dt)

def _find_transition_time(dt_lo: datetime, dt_hi: datetime, tithi_target: int, want_start: bool) -> datetime:
    """
    Binary search minute-precision transition boundary between two datetimes where tithi changes.
    want_start=True  -> find first minute where tithi==tithi_target
    want_start=False -> find first minute where tithi!=tithi_target (i.e. end boundary)
    """
    # assume dt_lo < dt_hi
    while (dt_hi - dt_lo).total_seconds() > 60:
        mid = dt_lo + (dt_hi - dt_lo) / 2
        mid = mid.replace(second=0, microsecond=0)

        t_mid = _tithi_at(mid)
        if want_start:
            # we want earliest time when tithi==target
            if t_mid == tithi_target:
                dt_hi = mid
            else:
                dt_lo = mid
        else:
            # we want earliest time when tithi!=target (end boundary)
            if t_mid != tithi_target:
                dt_hi = mid
            else:
                dt_lo = mid

    return dt_hi.replace(second=0, microsecond=0)



def get_tithi_window_for_day(day_date: datetime, target_tithi: int):
    """
    Finds start/end time of target_tithi around a given civil date (IST naive datetime).
    Uses coarse scan + binary refine. Returns (start_dt, end_dt) or (None, None) if not found.
    """
    day_start = day_date.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    # Coarse scan every 10 minutes across [day_start-6h, day_end+6h] to catch boundary near edges
    scan_start = day_start - timedelta(hours=6)
    scan_end = day_end + timedelta(hours=6)
    step = timedelta(minutes=10)

    found_any = False
    first_in = None
    last_in = None

    dt = scan_start
    while dt <= scan_end:
        if _tithi_at(dt) == target_tithi:
            found_any = True
            if first_in is None:
                first_in = dt
            last_in = dt
        dt += step

    if not found_any:
        return None, None

    # Refine start: search within [first_in-step, first_in+step]
    lo = first_in - step
    hi = first_in + step
    start_dt = _find_transition_time(lo, hi, target_tithi, want_start=True)

    # Refine end: search within [last_in, last_in+2*step] until it changes
    # ensure we bracket the end
    lo = last_in
    hi = last_in + timedelta(minutes=60)
    while _tithi_at(hi) == target_tithi and hi < scan_end + timedelta(hours=6):
        hi += timedelta(minutes=60)

    end_dt = _find_transition_time(lo, hi, target_tithi, want_start=False)
    return start_dt, end_dt

def _sunrise_dt_from_panchang(p):
    if not p:
        return None
    d = p.get("date")
    sr = p.get("sunrise")
    if not d or not sr:
        return None
    return datetime.strptime(f"{d} {sr}", "%Y-%m-%d %H:%M")


def determine_ekadashi_observance(panchang_today, lat, lon, language="en"):
    """
    Returns:
    {
      "smarta_date": "YYYY-MM-DD",
      "vaishnav_date": "YYYY-MM-DD",
      "reason": "..."
    }
    """

    date_str = panchang_today.get("date")
    if not date_str:
        return None

    # --- Sunrise Today ---
    sunrise_today = _sunrise_dt_from_panchang(panchang_today)
    if not sunrise_today:
        return None

    today_date = datetime.strptime(date_str, "%Y-%m-%d")
    t_today = _tithi_at(sunrise_today)


    # --- Sunrise Next Day ---
    next_date = today_date + timedelta(days=1)
    p_next = calculate_panchang(next_date.date(), lat, lon, language)

    sunrise_next = _sunrise_dt_from_panchang(p_next)
    if not sunrise_next:
        return None

    t_next = _tithi_at(sunrise_next)

    # --- Smarta Rule ---
    if t_today in EKADASHI_NUMBERS:
        smarta = _fmt_date(today_date)
        reason = "Ekadashi tithi present at today's sunrise (Smarta rule)."

    elif t_next in EKADASHI_NUMBERS:
        smarta = _fmt_date(next_date)
        reason = "Ekadashi tithi present at next day's sunrise (Smarta rule)."

    else:
        return None

    # --- Vaishnav Rule (overlap handling) ---
    if (t_today in EKADASHI_NUMBERS) and (t_next in EKADASHI_NUMBERS):
        vaishnav = _fmt_date(next_date)
    elif t_today in EKADASHI_NUMBERS:
        vaishnav = _fmt_date(today_date)
    else:
        vaishnav = _fmt_date(next_date)

    return {
        "smarta_date": smarta,
        "vaishnav_date": vaishnav,
        "reason": reason
    }

def calculate_parana_window(observed_date_str: str, lat, lon, language="en"):
    """
    Auto Parana on next civil day:
      start = max(Dwadashi start, (Hari-vasara end))  [we'll compute Hari-vasara end]
      end   = Dwadashi end
    Returns dict or None.
    """
    obs_date = datetime.strptime(observed_date_str, "%Y-%m-%d")
    parana_date = obs_date + timedelta(days=1)

    # We need Dwadashi (12 or 27). Determine which based on paksha at sunrise.
    p_next = calculate_panchang(parana_date.date(), lat, lon, language)
    sunrise_dt = _sunrise_dt_from_panchang(p_next)
    if not sunrise_dt:
        return None
    t_sun = _tithi_at(sunrise_dt)
    

    # choose correct Dwadashi number (12 for Shukla, 27 for Krishna)
    # We infer: if sunrise tithi is 12 or 27, use that. Otherwise, still try both and pick the one present that day.
    candidates = []
    if t_sun in DWADASHI_NUMBERS:
        candidates = [t_sun]
    else:
        candidates = list(DWADASHI_NUMBERS)

    dw_start = dw_end = None
    dw_num = None
    for cand in candidates:
        s, e = get_tithi_window_for_day(parana_date, cand)
        if s and e:
            dw_start, dw_end, dw_num = s, e, cand
            break

    if not dw_start or not dw_end:
        return None

    # Hari Vasara end = Dwadashi start + 1/4 of Dwadashi duration
    dw_duration = dw_end - dw_start
    hari_vasara_end = dw_start + (dw_duration / 4)

    # Parana start should be after both Dwadashi start & Hari Vasara end.
    parana_start = max(dw_start, hari_vasara_end, sunrise_dt)

    # Practical safety: if parana_start >= dw_end -> no valid window
    if parana_start >= dw_end:
        return None

    return {
        "date": _fmt_date(parana_date),
        "start": _fmt_dt(parana_start),
        "end": _fmt_dt(dw_end),
        "hari_vasara_end": _fmt_dt(hari_vasara_end),
        "dwadashi_tithi_number": dw_num,
        "sunrise": _fmt_dt(sunrise_dt),
    }

# -----------------------------
# FINAL: Single JSON builder
# -----------------------------

def build_ekadashi_json(panchang_today, lat, lon, language="en"):

    obs = determine_ekadashi_observance(panchang_today, lat, lon, language)
    if not obs:
        return None

    vrat_date = obs["smarta_date"]

    vrat_dt = datetime.strptime(vrat_date, "%Y-%m-%d")
    p_vrat = calculate_panchang(vrat_dt.date(), lat, lon, language)

    # --- Get Paksha FIRST ---
    paksha = p_vrat.get("tithi", {}).get("paksha")
    if not paksha:
        return None

    if paksha.startswith("शुक्ल"):
        paksha = "Shukla"
    elif paksha.startswith("कृष्ण"):
        paksha = "Krishna"

    # --- First calculate Parana ---
    parana = calculate_parana_window(vrat_date, lat, lon, language)

    # Month must be taken from Ekadashi sunrise (Shastriya rule)
    sunrise_dt = _sunrise_dt_from_panchang(p_vrat)
    if not sunrise_dt:
        return None

    month = get_lunar_month(sunrise_dt)
    if not month:
        return None

    # --- Map Ekadashi Name ---
    key = (month, paksha)
    if key not in EKADASHI_MAP:
        print("DEBUG EKADASHI KEY NOT FOUND:", key)
        return None

    name_en, name_hi = EKADASHI_MAP[key]

    return {
        "type": "ekadashi",
        "name_en": name_en,
        "name_hi": name_hi,
        "slug": slugify(name_en),
        "vrat_date": vrat_date,
        "parana": None if not parana else {
            "date": parana["date"],
            "start": parana["start"],
            "end": parana["end"],
        },
        "observance": obs,
        "tithi": {
            "start": p_vrat.get("tithi", {}).get("start_ist"),
            "end": p_vrat.get("tithi", {}).get("end_ist"),
            "paksha": paksha,
            "month": month,
        },
        "sunrise": p_vrat.get("sunrise"),
        "internal": None if not parana else {
            "hari_vasara_end": parana["hari_vasara_end"],
            "dwadashi_tithi_number": parana["dwadashi_tithi_number"],
            "parana_sunrise": parana["sunrise"],
        }
    }

# ==========================================================
# PRADOSH DETECTOR
# ==========================================================

def get_pradosh_details(panchang_data):
    try:
        sunset_time = panchang_data.get("sunset")
        date_str = panchang_data.get("date")

        if not (sunset_time and date_str):
            return None

        # Create sunset datetime
        sunset_dt = datetime.strptime(
            f"{date_str} {sunset_time}",
            "%Y-%m-%d %H:%M"
        )

        # 🔥 Get tithi at sunset (NOT noon)
        from services.panchang_engine import _tithi_number_at
        tithi_at_sunset = _tithi_number_at(sunset_dt)

        if tithi_at_sunset not in (13, 28):
            return None

        paksha = "Shukla" if tithi_at_sunset <= 15 else "Krishna"

        name_en = f"{paksha} Pradosh Vrat"
        name_hi = "शुक्ल प्रदोष व्रत" if paksha == "Shukla" else "कृष्ण प्रदोष व्रत"

        return {
            "type": "pradosh",
            "name_en": name_en,
            "name_hi": name_hi,
            "slug": "pradosh-vrat",
            "date": date_str,
            "paksha": paksha,
            "sunset_time": sunset_time,
            "tithi_at_sunset": tithi_at_sunset,
        }

    except Exception:
        return None


def find_next_pradosh(start_date, lat, lon, language="en", days_ahead=45):

    for i in range(1, days_ahead + 1):
        check_date = start_date + timedelta(days=i)

        panchang = calculate_panchang(check_date, lat, lon, language)

        pradosh = get_pradosh_details(panchang)

        if pradosh:
            return pradosh

    return None

# ==========================================================
# SANKASHTI CHATURTHI DETECTOR
# ==========================================================

def get_sankashti_details(panchang_data, lat, lon):

    try:
        date_str = panchang_data.get("date")
        if not date_str:
            return None 

        event_date = datetime.strptime(date_str, "%Y-%m-%d")

        # 1️⃣ Get Moonrise (IST)
        moon_data = get_moon_rise_set(event_date, lat, lon)
        if not moon_data:
            return None

        moonrise_str = moon_data.get("moonrise")
        if not moonrise_str:
            return None

        moonrise_dt = datetime.strptime(
            f"{date_str} {moonrise_str}",
            "%Y-%m-%d %I:%M %p"
        )

        # 2️⃣ Directly check Tithi at moonrise (NO manual UT conversion)
        tithi_at_moonrise = _tithi_number_at(moonrise_dt)

        # Krishna Chaturthi = 19
        if tithi_at_moonrise != 19:
            return None

        vrat_date = moonrise_dt.date()

        return {
            "type": "sankashti",
            "date": vrat_date.strftime("%Y-%m-%d"),
            "moonrise_time": moonrise_dt.strftime("%H:%M"),
            "paran_time": moonrise_dt.strftime("%H:%M"),
            "is_angaraki": vrat_date.weekday() == 1,
        }

    except Exception:
        return None


# ==========================================================
# FIND NEXT SANKASHTI
# ==========================================================

def find_next_sankashti(start_date, lat, lon, language="en", days_ahead=45):

    for i in range(1, days_ahead + 1):
        check_date = start_date + timedelta(days=i)

        panchang = calculate_panchang(check_date, lat, lon, language)

        sankashti = get_sankashti_details(panchang, lat, lon)

        if sankashti:
            return sankashti

    return None

# ==========================================================
# AMAVASYA DETECTOR
# ==========================================================

def get_amavasya_details(panchang_data):
    try:
        t = panchang_data.get("tithi") or {}
        if int(t.get("number", 0)) != 30:
            return None

        date_str = panchang_data.get("date")
        if not date_str:
            return None

        weekday = panchang_data.get("weekday")

        special_type = None
        special_name_en = None
        special_name_hi = None

        if weekday in ("Monday", "सोमवार"):
            special_type = "somvati_amavasya"
            special_name_en = "Somvati Amavasya"
            special_name_hi = "सोमवती अमावस्या"

        elif weekday in ("Saturday", "शनिवार"):
            special_type = "shani_amavasya"
            special_name_en = "Shani Amavasya"
            special_name_hi = "शनि अमावस्या"

        elif weekday in ("Tuesday", "मंगलवार"):
            special_type = "bhaum_amavasya"
            special_name_en = "Bhaum Amavasya"
            special_name_hi = "भौम अमावस्या"

        return {
            "type": "amavasya",
            "date": date_str,
            "name_en": "Amavasya",
            "name_hi": "अमावस्या",
            "slug": "amavasya",
            "tithi_start": t.get("start_ist"),
            "tithi_end": t.get("end_ist"),
            "paksha": t.get("paksha"),

            # 🔥 New optional enrichment
            "special_type": special_type,
            "special_name_en": special_name_en,
            "special_name_hi": special_name_hi,
        }

    except Exception:
        return None

# ==========================================================
# FIND NEXT AMAVASYA
# ==========================================================

def find_next_amavasya(start_date, lat, lon, language="en", days_ahead=60):

    for i in range(1, days_ahead + 1):
        check_date = start_date + timedelta(days=i)

        panchang = calculate_panchang(check_date, lat, lon, language)

        amavasya = get_amavasya_details(panchang)

        if amavasya:
            return amavasya

    return None

# ==========================================================
# PURNIMA DETECTOR
# ==========================================================

def get_purnima_details(panchang_data):
    try:
        t = panchang_data.get("tithi") or {}

        # Shukla Purnima = 15
        if int(t.get("number", 0)) != 15:
            return None

        date_str = panchang_data.get("date")
        if not date_str:
            return None

        return {
            "type": "purnima",
            "date": date_str,
            "name_en": "Purnima",
            "name_hi": "पूर्णिमा",
            "slug": "purnima",
            "tithi_start": t.get("start_ist"),
            "tithi_end": t.get("end_ist"),
            "paksha": t.get("paksha"),
        }

    except Exception:
        return None

def find_next_purnima(start_date, lat, lon, language="en", days_ahead=60):

    for i in range(1, days_ahead + 1):
        check_date = start_date + timedelta(days=i)

        panchang = calculate_panchang(check_date, lat, lon, language)

        purnima = get_purnima_details(panchang)

        if purnima:
            return purnima

    return None

# ==========================================================
# VINAYAKA / GANESH CHATURTHI DETECTOR
# ==========================================================

def get_vinayaka_chaturthi_details(panchang_data):
    try:
        t = panchang_data.get("tithi") or {}
        tithi_number = int(t.get("number", 0))

        # Shukla Chaturthi = 4
        if tithi_number != 4:
            return None

        date_str = panchang_data.get("date")
        if not date_str:
            return None

        month = panchang_data.get("month_name")

        # 🔥 Special case: Bhadrapada Shukla Chaturthi
        if month in ("Bhadrapada", "भाद्रपद"):
            name_en = "Ganesh Chaturthi"
            name_hi = "गणेश चतुर्थी"
            slug = "ganesh-chaturthi"
        else:
            name_en = "Vinayaka Chaturthi"
            name_hi = "विनायक चतुर्थी"
            slug = "vinayaka-chaturthi"

        return {
            "type": "vinayaka_chaturthi",
            "date": date_str,
            "name_en": name_en,
            "name_hi": name_hi,
            "slug": slug,
            "tithi_start": t.get("start_ist"),
            "tithi_end": t.get("end_ist"),
            "paksha": t.get("paksha"),
            "month": month,
        }

    except Exception:
        return None
    
def find_next_vinayaka_chaturthi(start_date, lat, lon, language="en", days_ahead=60):

    for i in range(1, days_ahead + 1):
        check_date = start_date + timedelta(days=i)

        panchang = calculate_panchang(check_date, lat, lon, language)

        chaturthi = get_vinayaka_chaturthi_details(panchang)

        if chaturthi:
            return chaturthi

    return None

# ==========================================================
# SHIVRATRI DETECTOR (Masik + Maha)
# ==========================================================

def get_shivratri_details(panchang_data, lat, lon, language="en"):
    try:
        date_str = panchang_data.get("date")
        if not date_str:
            return None

        night_dt = datetime.strptime(f"{date_str} 23:30", "%Y-%m-%d %H:%M")

        shiv_type, lunar_month = get_shivratri_type(night_dt)

        if not shiv_type:
            return None

        tithi = panchang_data.get("tithi") or {}

        if shiv_type == "maha_shivratri":
            name_en = "Maha Shivratri"
            name_hi = "महाशिवरात्रि"
            slug = "maha-shivratri"
        else:
            name_en = "Masik Shivratri"
            name_hi = "मासिक शिवरात्रि"
            slug = "masik-shivratri"

        return {
            "type": shiv_type,
            "date": date_str,
            "name_en": name_en,
            "name_hi": name_hi,
            "slug": slug,
            "month": lunar_month,
            "tithi_start": tithi.get("start_ist"),
            "tithi_end": tithi.get("end_ist"),
        }

    except Exception:
        return None


def find_next_shivratri(start_date, lat, lon, language="en", days_ahead=90):
    for i in range(1, days_ahead + 1):
        check_date = start_date + timedelta(days=i)
        p = calculate_panchang(check_date, lat, lon, language)
        hit = get_shivratri_details(p, lat, lon, language)
        if hit:
            return hit
    return None
