import re
from datetime import datetime, timedelta
from services.panchang_engine import calculate_panchang, _tithi_number_at
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

    # DRIK PANCHANG (North India) MATCHING LOGIC
    # Engine Amanta hai, Drik Purnimanta hai. 
    # Dono Paksha (Krishna aur Shukla) ko 1 step aage shift karna padta hai 
    # engine ke mahine se align karne ke liye.
    try:
        current_idx = HINDU_MONTHS.index(engine_month)
        display_month = HINDU_MONTHS[(current_idx + 1) % 12]
    except ValueError:
        display_month = engine_month

    return EKADASHI_MAP.get((display_month, paksha_key), ("Ekadashi", "एकादशी"))


# --- Helpers ---
def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")

def _sunrise_dt(p):
    return datetime.strptime(f"{p['date']} {p['sunrise']}", "%Y-%m-%d %H:%M")

def _fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")

# --- Parana & Observance Logic ---
def calculate_parana_window(vrat_date_obj, lat, lon):
    parana_day = vrat_date_obj + timedelta(days=1)
    p_parana = calculate_panchang(parana_day, lat, lon)
    sr_parana = _sunrise_dt(p_parana)
    
    dwadashi_start = datetime.strptime(p_parana["tithi"]["start_ist"], "%Y-%m-%d %H:%M")
    dwadashi_end = datetime.strptime(p_parana["tithi"]["end_ist"], "%Y-%m-%d %H:%M")
    
    dw_duration = dwadashi_end - dwadashi_start
    hari_vasara_end = dwadashi_start + (dw_duration / 4)
    
    p_start = max(sr_parana, hari_vasara_end)
    p_end = dwadashi_end
    
    if p_start > p_end:
        p_end = p_start + timedelta(hours=2)

    return {
        "parana_date": parana_day.strftime("%Y-%m-%d"),
        "start": _fmt_dt(p_start),
        "end": _fmt_dt(p_end),
        "hari_vasara_end": _fmt_dt(hari_vasara_end)
    }

def determine_ekadashi_observance(date_obj, lat, lon):
    p_today = calculate_panchang(date_obj, lat, lon)
    sr_today = _sunrise_dt(p_today)
    
    # 1. Agle din ka sunrise (Dynamic check ke liye)
    p_next = calculate_panchang(date_obj + timedelta(days=1), lat, lon)
    sr_next = _sunrise_dt(p_next)
    
    # 2. Arunodaya (96 mins before Sunrise)
    arunodaya_today = sr_today - timedelta(minutes=96)
    
    t_arunodaya = _tithi_number_at(arunodaya_today)
    t_sunrise = _tithi_number_at(sr_today)
    t_sunrise_next = _tithi_number_at(sr_next)
    
    # --- A. Trisparsha Mahadwadashi ---
    # Logic: Ek hi din (Sunrise se Next Sunrise) mein 11, 12 aur 13 teeno touch ho jayein
    # Hum check karenge ki sunrise ke JUST pehle 11 thi, aur next sunrise se JUST pehle 13 shuru ho gayi
    t_just_before_next_sr = _tithi_number_at(sr_next - timedelta(minutes=1))
    if t_sunrise in (11, 26) and t_just_before_next_sr in (13, 28):
        return "Trisparsha Mahadwadashi", date_obj

    # --- B. Dashami Vedha (Viddha Ekadashi) ---
    if t_sunrise in (11, 26):
        # Agar Arunodaya mein Dashami (10/25) hai, toh ye "Viddha" hai -> Is din vrat nahi hoga
        if t_arunodaya in (10, 25):
            # Vrat agle din shift hoga, par sirf tab jab agle din sunrise par 11 ya 12 ho
            if t_sunrise_next in (11, 12, 26, 27):
                return "Gauna/Vaishnava", date_obj + timedelta(days=1)
            return None, None # Rare case jahan tithi kshaya ho gayi
        
        # --- C. Unmilini Mahadwadashi ---
        # Agar aaj bhi Ekadashi hai aur kal sunrise par bhi Ekadashi hai
        if t_sunrise_next in (11, 26):
            return "Unmilini Mahadwadashi", date_obj + timedelta(days=1)
        
        # Regular Shuddh Ekadashi
        return "Regular", date_obj

    # --- D. Pakshavarddhini Mahadwadashi ---
    # Jab Ekadashi sunrise se pehle shuru ho kar sunrise ke baad khatam ho (Dwadashi at sunrise)
    # Aur agle din bhi Dwadashi hi rahe (Dwadashi vriddhi)
    if t_sunrise in (12, 27):
        p_prev = calculate_panchang(date_obj - timedelta(days=1), lat, lon)
        t_sr_prev = _tithi_number_at(_sunrise_dt(p_prev))
        
        # Agar kal Ekadashi thi aur aaj Dwadashi hai, aur kal bhi Dwadashi rahegi
        if t_sr_prev in (11, 26) and t_sunrise_next in (12, 27):
             return "Pakshavarddhini Mahadwadashi", date_obj

    return None, None

# --- Main Builder ---
def build_ekadashi_json(date_obj, lat, lon, language="en"):
    # Convert date_obj to string for foolproof comparison
    target_date_str = date_obj.strftime("%Y-%m-%d") if hasattr(date_obj, 'strftime') else str(date_obj)

    for check_day in [date_obj - timedelta(days=1), date_obj]:
        vrat_type, final_date = determine_ekadashi_observance(check_day, lat, lon)
        
        if final_date:
            # 1. Sabse pehle string bana lo
            actual_date_str = final_date.strftime("%Y-%m-%d")
            
            # 2. Panchang ke liye sirf DATE object ensure karein
            if isinstance(final_date, datetime):
                actual_date_for_panchang = final_date.date()
            else:
                actual_date_for_panchang = final_date

            # 3. Safe Comparison: Agar ye wahi din hai jise loop scan kar raha hai
            if actual_date_str == target_date_str:
                p_vrat = calculate_panchang(actual_date_for_panchang, lat, lon, language)
                sr_vrat = _sunrise_dt(p_vrat)
                
                # ADHIK MAAS DETECTION
                month_data = get_lunar_month(sr_vrat) 
                month = month_data['name']
                is_adhik = month_data['is_adhik']
                
                t_num = p_vrat['tithi']['number']
                paksha = "Shukla" if (0 < t_num <= 15) or (30 < t_num <= 45) else "Krishna"
                
                # Dynamic Name using your corrected get_ekadashi_name
                base_name_en, name_hi = get_ekadashi_name(month, t_num, is_adhik)
                
                # Formatting name for Mahadwadashis
                if is_adhik:
                    full_name_en = base_name_en
                else:
                    # Agar Regular nahi hai toh special type (e.g. Trisparsha) pehle jodo
                    full_name_en = base_name_en if vrat_type == "Regular" else f"{vrat_type.replace('/', ', ')}, {base_name_en}"
                
                parana_data = calculate_parana_window(actual_date_for_panchang, lat, lon)

                return {
                    "type": "ekadashi",
                    "name_en": full_name_en,
                    "name_hi": name_hi,
                    "slug": slugify(base_name_en),
                    "vrat_date": actual_date_str,
                    "tithi": {
                        "start": p_vrat["tithi"]["start_ist"],
                        "end": p_vrat["tithi"]["end_ist"],
                        "paksha": paksha,
                        "month": month,
                        "is_adhik": is_adhik
                    },
                    "parana": parana_data
                }
    return None

def generate_year(year: int, lat: float, lon: float, language: str = "en"):
    # START DATE KO DATE OBJECT BANAYA
    current = datetime(year, 1, 1).date()
    end_date = datetime(year, 12, 31).date()
    
    raw_results = []
    
    # 1. Pehle saari possible Ekadashis dhoondo
    while current <= end_date:
        # Loop ke 'current' ko build_ekadashi_json mein bhej rahe hain
        r = build_ekadashi_json(current, lat, lon, language)
        if r:
            # Check for duplicates
            if not any(res['vrat_date'] == r['vrat_date'] for res in raw_results):
                raw_results.append(r)
        current += timedelta(days=1)

    if not raw_results:
        # Crash hone se bachane ke liye print statement
        print(f"--- DEBUG: No Ekadashi found for {year} ---")
        return {"year": year, "count": 0, "ekadashi_list": []}

    # 2. Drik Panchang Filter: Mahadwadashi Merge Logic
    final_list = []
    i = 0
    while i < len(raw_results):
        skip_current = False
        if i + 1 < len(raw_results):
            curr = raw_results[i]
            nxt = raw_results[i+1]
            
            # String date ko compare karne ke liye parse karna
            d1 = datetime.strptime(curr["vrat_date"], "%Y-%m-%d").date()
            d2 = datetime.strptime(nxt["vrat_date"], "%Y-%m-%d").date()
            
            # Agar consecutive dates hain aur agla Mahadwadashi hai
            if (d2 - d1).days == 1 and "Mahadwadashi" in nxt["name_en"]:
                final_list.append(nxt)
                i += 2
                skip_current = True
        
        if not skip_current:
            final_list.append(raw_results[i])
            i += 1

    return {
        "year": year, 
        "count": len(final_list), 
        "ekadashi_list": final_list
    }
