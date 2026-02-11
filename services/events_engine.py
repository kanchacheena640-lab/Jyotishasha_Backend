# services/events_engine.py

from datetime import datetime, timedelta
from services.panchang_engine import calculate_panchang

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
    """
    Detect Pradosh Vrat:
    Trayodashi (13 / 28) must be active at local sunset.
    """

    try:
        tithi = panchang_data.get("tithi", {})
        tithi_number = tithi.get("number")

        # 13 = Shukla Trayodashi
        # 28 = Krishna Trayodashi
        if tithi_number not in (13, 28):
            return None

        tithi_start = tithi.get("start_ist")
        tithi_end = tithi.get("end_ist")
        sunset = panchang_data.get("sunset")

        if not (tithi_start and tithi_end and sunset):
            return None

        # Parse datetime safely
        tithi_start_dt = datetime.strptime(tithi_start, "%Y-%m-%d %H:%M")
        tithi_end_dt   = datetime.strptime(tithi_end, "%Y-%m-%d %H:%M")
        sunset_dt      = datetime.strptime(sunset, "%Y-%m-%d %H:%M")

        # Sunset must fall inside Trayodashi window
        if sunset_dt < tithi_start_dt or sunset_dt > tithi_end_dt:
            return None

        paksha = tithi.get("paksha")

        if paksha in ("शुक्ल पक्ष",):
            paksha = "Shukla"
        elif paksha in ("कृष्ण पक्ष",):
            paksha = "Krishna"

        name_en = f"{paksha} Pradosh Vrat"
        name_hi = "शुक्ल प्रदोष व्रत" if paksha == "Shukla" else "कृष्ण प्रदोष व्रत"

        return {
            "type": "pradosh",
            "name_en": name_en,
            "name_hi": name_hi,
            "slug": "pradosh-vrat",
            "date": panchang_data.get("date"),
            "tithi_start": tithi_start,
            "tithi_end": tithi_end,
            "paksha": paksha,
        }

    except Exception:
        # Never break API if parsing fails
        return None

def find_next_pradosh(start_date, lat, lon, language="en", days_ahead=45):

    for i in range(1, days_ahead + 1):
        check_date = start_date + timedelta(days=i)

        panchang = calculate_panchang(check_date, lat, lon, language)

        pradosh = get_pradosh_details(panchang)

        if pradosh:
            return pradosh

    return None