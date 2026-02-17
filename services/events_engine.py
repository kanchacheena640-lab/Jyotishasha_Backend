# services/events_engine.py

from datetime import datetime, timedelta
from services.panchang_engine import calculate_panchang, _tithi_number_at
from services.moon_calc import get_moon_rise_set

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

# ==========================================================
# EKADASHI DETECTOR
# ==========================================================

def get_ekadashi_details(panchang_data):
    """
    Accepts single-day Panchang (calculate_panchang output)
    Returns structured Ekadashi object or None
    """

    tithi_number = panchang_data["tithi"]["number"]

    # 11 = Shukla Ekadashi
    # 26 = Krishna Ekadashi (11 + 15)
    if tithi_number not in (11, 26):
        return None

    # Normalize month (Hindi → English safe)
    month = panchang_data.get("month_name")
    month = HINDI_MONTH_TO_EN.get(month, month)

    paksha = panchang_data["tithi"]["paksha"]

    # Normalize paksha if Hindi
    if paksha in ("शुक्ल पक्ष",):
        paksha = "Shukla"
    elif paksha in ("कृष्ण पक्ष",):
        paksha = "Krishna"

    key = (month, paksha)

    if key not in EKADASHI_MAP:
        return None

    name_en, name_hi = EKADASHI_MAP[key]

    return {
        "type": "ekadashi",
        "name_en": name_en,
        "name_hi": name_hi,
        "slug": name_en.lower().replace(" ", "-"),
        "date": panchang_data["date"],
        "tithi_start": panchang_data["tithi"]["start_ist"],
        "tithi_end": panchang_data["tithi"]["end_ist"],
        "month": month,
        "paksha": paksha,
    }

# ==========================================================
# FIND NEXT EKADASHI
# ==========================================================

def find_next_ekadashi(start_date, lat, lon, language="en", days_ahead=45):
    """
    Scan forward to find next Ekadashi.
    Default scan = 45 days (safe window).
    """

    language = (language or "en").lower()
    if language not in ("en", "hi"):
        language = "en"

    for i in range(1, days_ahead + 1):
        check_date = start_date + timedelta(days=i)

        panchang = calculate_panchang(check_date, lat, lon, language)

        ekadashi = get_ekadashi_details(panchang)

        if ekadashi:
            return ekadashi

    return None
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

        return {
            "type": "amavasya",
            "date": date_str,
            "name_en": "Amavasya",
            "name_hi": "अमावस्या",
            "slug": "amavasya",
            "tithi_start": t.get("start_ist"),
            "tithi_end": t.get("end_ist"),
            "paksha": t.get("paksha"),
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

        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        month_name = panchang_data.get("month_name")

        # 🔥 Check tithi during late night (Shivratri rule)
        night_dt = datetime.strptime(f"{date_str} 23:30", "%Y-%m-%d %H:%M")
        tithi_night = _tithi_number_at(night_dt)

        if tithi_night != 29:
            return None

        # 🔥 NEW: get month at night (not sunrise)
        night_panchang = calculate_panchang(d, lat, lon, language, ref_dt_ist=night_dt)
        night_month = night_panchang.get("month_name")

        # Default = Masik Shivratri
        event_type = "masik_shivratri"
        name_en = "Masik Shivratri"
        name_hi = "मासिक शिवरात्रि"
        slug = "masik-shivratri"

        # Maha Shivratri = Krishna Chaturdashi just before Amavasya
        next_day_dt = night_dt + timedelta(days=1)
        next_tithi = _tithi_number_at(next_day_dt)

        if next_tithi == 30:
            event_type = "maha_shivratri"
            name_en = "Maha Shivratri"
            name_hi = "महाशिवरात्रि"
            slug = "maha-shivratri"

        t = panchang_data.get("tithi") or {}

        return {
            "type": event_type,
            "date": date_str,
            "name_en": name_en,
            "name_hi": name_hi,
            "slug": slug,
            "month": night_month,
            "tithi_start": t.get("start_ist"),
            "tithi_end": t.get("end_ist"),
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

