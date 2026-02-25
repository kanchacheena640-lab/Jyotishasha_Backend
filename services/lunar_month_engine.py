from datetime import datetime, timedelta
import swisseph as swe
from services.astro_core import _tithi_number_at, sidereal_longitudes

HINDU_MONTHS = [
    "Chaitra", "Vaishakha", "Jyeshtha", "Ashadha",
    "Shravana", "Bhadrapada", "Ashwin", "Kartik",
    "Margashirsha", "Pausha", "Magha", "Phalguna"
]

def _sun_rashi_index(dt_ist):
    sun, _ = sidereal_longitudes(dt_ist)
    return int(sun // 30) % 12

def _find_amavasya_boundary(dt_ist, direction="past"):
    """
    Finds the exact end time of the nearest Amavasya using Binary Search.
    Full-proof method to detect month boundaries.
    """
    step = timedelta(days=1)
    t1 = dt_ist
    # Scan for the transition from Tithi 30 to Tithi 1
    for _ in range(40):
        t0 = t1 - step if direction == "past" else t1 + step
        if direction == "past":
            if _tithi_number_at(t0) == 30 and _tithi_number_at(t1) != 30:
                break
        else:
            if _tithi_number_at(t1) == 30 and _tithi_number_at(t0) != 30:
                break
        t1 = t0
    
    # Binary search for precision
    low, high = (t0, t1) if direction == "past" else (t1, t0)
    for _ in range(25):
        mid = low + (high - low) / 2
        if _tithi_number_at(mid) == 30:
            low = mid
        else:
            high = mid
    return high

def get_lunar_month(dt_ist):
    """
    Full-proof Purnimanta Month engine. 
    Detects Adhik Maas by checking solar ingress between New Moons.
    """
    # 1. Is month ki boundary dhundho (Amavasya to Amavasya)
    last_amavasya = _find_amavasya_boundary(dt_ist, "past")
    next_amavasya = _find_amavasya_boundary(dt_ist, "future")

    # 2. Solar Rashi at both ends (Adhik Maas Detection)
    # Agar dono Amavasya ke waqt Sun ki Rashi same hai = ADHIK MAAS
    rashi_start = _sun_rashi_index(last_amavasya + timedelta(minutes=5))
    rashi_end = _sun_rashi_index(next_amavasya - timedelta(minutes=5))
    
    is_adhik = (rashi_start == rashi_end)
    
    # 3. Amanta Index
    amanta_index = rashi_start
    
    # 4. Purnimanta Shift (Krishna Paksha logic)
    tithi = _tithi_number_at(dt_ist)
    month_index = amanta_index
    if tithi > 15:
        # Krishna Paksha belongs to next month in North India
        month_index = (amanta_index + 1) % 12

    return {
        "name": HINDU_MONTHS[month_index],
        "is_adhik": is_adhik,
        "amanta_index": amanta_index
    }

def get_shivratri_type(dt_ist):
    tithi_number = _tithi_number_at(dt_ist)
    if tithi_number != 29:
        return None, None

    lunar_month = get_lunar_month(dt_ist)
    # Maha Shivratri Phalguna Krishna Chaturdashi ko hoti hai (Purnimanta context)
    if lunar_month == "Phalguna":
        return "maha_shivratri", lunar_month

    return "masik_shivratri", lunar_month

def get_amanta_month(dt_ist):
    # 1. Is lunar cycle ki boundaries
    last_amavasya = _find_amavasya_boundary(dt_ist, "past")
    next_amavasya = _find_amavasya_boundary(dt_ist, "future")

    # 2. Solar Rashi at boundary ends
    rashi_start = _sun_rashi_index(last_amavasya + timedelta(minutes=5))
    rashi_end = _sun_rashi_index(next_amavasya - timedelta(minutes=5))
    
    # ADHIK MAAS: Agar lunar month ke beech koi Sankranti (Rashi change) nahi hui
    is_adhik = (rashi_start == rashi_end)
    
    # VEDIC RULE: Month name is determined by the NEXT Solar Ingress (Sankranti)
    # Rashi 11 (Pisces) means Chaitra (Index 0) is coming.
    month_index = (rashi_start + 1) % 12 

    return {
        "name": HINDU_MONTHS[month_index],
        "is_adhik": is_adhik,
        "index": month_index
    }