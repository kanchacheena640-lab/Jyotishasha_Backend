# services/events_engine.py

from datetime import datetime, timedelta
from services.panchang_engine import calculate_panchang, _tithi_number_at
from services.moon_calc import get_moonrise

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
        event_date = datetime.strptime(date_str, "%Y-%m-%d")

        moonrise_dt = get_moonrise(event_date, lat, lon)
        if not moonrise_dt:
            return None

        # DECISIVE CHECK
        tithi_at_moonrise = _tithi_number_at(moonrise_dt)

        # Krishna Chaturthi = 19
        if tithi_at_moonrise != 19:
            return None

        is_angaraki = event_date.weekday() == 1

        name_en = "Angaraki Sankashti Chaturthi" if is_angaraki else "Sankashti Chaturthi"
        name_hi = "अंगारकी संकष्टी चतुर्थी" if is_angaraki else "संकष्टी चतुर्थी"

        return {
            "type": "sankashti",
            "name_en": name_en,
            "name_hi": name_hi,
            "slug": "sankashti-chaturthi",
            "date": date_str,
            "is_angaraki": is_angaraki,
            "moonrise_time": moonrise_dt.strftime("%H:%M"),
            "paran_time": moonrise_dt.strftime("%H:%M"),
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
