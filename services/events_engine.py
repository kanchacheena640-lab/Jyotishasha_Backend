# services/events_engine.py

from datetime import datetime, timedelta
from services.panchang_engine import calculate_panchang, _tithi_number_at
from services.moon_calc import get_moon_rise_set
from services.lunar_month_engine import get_shivratri_type



def parse_datetime_safe(dt_str):
    if not dt_str:
        return None

    dt_str = str(dt_str).strip()

    # 🔥 FIX corrupt patterns
    dt_str = dt_str.replace("  ", " ")
    dt_str = dt_str.replace("20 026", "2026")
    dt_str = dt_str.replace("22026", "2026")
    dt_str = dt_str.replace(" 5-", "-")

    formats = [
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d%H:%M",
        "%Y-%m-%d %H:%M:%S"
    ]

    for fmt in formats:
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            continue

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
            "date": datetime.strptime(date_str, "%Y-%m-%d").strftime("%Y-%m-%d"),
            "paksha": paksha,
            "sunset_time": sunset_time,
            "tithi_at_sunset": tithi_at_sunset,
        }

    except Exception as e:
        print(f"❌ Error in {__name__}: {str(e)}")
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
        # 🔥 SAFE FIX
        date_str = str(date_str).replace("20   026", "2026").replace("20 026", "2026")
        
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

    except Exception as e:
        print(f"❌ Error in {__name__}: {str(e)}")
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

        # 🔥 Safe int conversion
        try:
            tithi_number = int(t.get("number", 0))
        except (TypeError, ValueError):
            return None

        if tithi_number != 30:
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
            "tithi_start": parse_datetime_safe(t.get("start_ist")),
            "tithi_end": parse_datetime_safe(t.get("end_ist")),
            "paksha": t.get("paksha"),

            # 🔥 New optional enrichment
            "special_type": special_type,
            "special_name_en": special_name_en,
            "special_name_hi": special_name_hi,
        }

    except Exception as e:
        print(f"❌ Error in {__name__}: {str(e)}")
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
        try:
            tithi_number = int(t.get("number", 0))
        except (TypeError, ValueError):
            return None

        if tithi_number != 15:   # (Vinayaka me 4)
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
            "tithi_start": parse_datetime_safe(t.get("start_ist")),
            "tithi_end": parse_datetime_safe(t.get("end_ist")),
            "paksha": t.get("paksha"),
        }

    except Exception as e:
        print(f"❌ Error in {__name__}: {str(e)}")
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
        try:
            tithi_number = int(t.get("number", 0))
        except (TypeError, ValueError):
            return None

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
            "tithi_start": parse_datetime_safe(t.get("start_ist")),
            "tithi_end": parse_datetime_safe(t.get("end_ist")),
            "paksha": t.get("paksha"),
            "month": month,
        }

    except Exception as e:
        print(f"❌ Error in {__name__}: {str(e)}")
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
            "tithi_start": parse_datetime_safe(tithi.get("start_ist")),
            "tithi_end": parse_datetime_safe(tithi.get("end_ist")),
        }

    except Exception as e:
        print(f"❌ Error in {__name__}: {str(e)}")
        return None


def find_next_shivratri(start_date, lat, lon, language="en", days_ahead=90):
    for i in range(1, days_ahead + 1):
        check_date = start_date + timedelta(days=i)
        p = calculate_panchang(check_date, lat, lon, language)
        hit = get_shivratri_details(p, lat, lon, language)
        if hit:
            return hit
    return None
