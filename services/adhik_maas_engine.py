from datetime import datetime, timedelta
from services.events_engine import find_next_amavasya
from services.sankranti_engine import get_sankranti_details
from services.lunar_month_engine import get_lunar_month
from services.lunar_month_engine import _sun_rashi_index

# ---------------------------------------------------------
# FIND ALL AMAVASYA IN A YEAR
# ---------------------------------------------------------

def _get_all_amavasya_of_year(year, lat, lon):
    amavasya_list = []

    current_date = datetime(year, 1, 1).date()
    end_date = datetime(year, 12, 31).date()

    while current_date <= end_date:
        hit = find_next_amavasya(current_date, lat, lon)

        if not hit:
            break

        amavasya_date = datetime.strptime(hit["date"], "%Y-%m-%d").date()

        if amavasya_date.year == year:
            amavasya_list.append(amavasya_date)

        current_date = amavasya_date + timedelta(days=1)

    return amavasya_list


# ---------------------------------------------------------
# CHECK IF SANKRANTI EXISTS BETWEEN TWO DATES
# ---------------------------------------------------------

def _has_sankranti_between(start_date, end_date, lat, lon):
    """
    Naam purana, Kaam naya! 
    Check if Sun entered a new Rashi between two Amavasya dates.
    """
    # 1. Start aur End ko datetime objects mein convert karo (agar string hain)
    # Hum dopahar 12 baje ka reference le rahe hain safety ke liye 
    # kyuki Amavasya ka exact time calculate_panchang ke bina milna mushkil hai yahan.
    if isinstance(start_date, str):
        start_dt = datetime.strptime(start_date, "%Y-%m-%d") + timedelta(hours=12)
    else:
        start_dt = datetime.combine(start_date, datetime.min.time()) + timedelta(hours=12)
        
    if isinstance(end_date, str):
        end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(hours=12)
    else:
        end_dt = datetime.combine(end_date, datetime.min.time()) + timedelta(hours=12)

    # 2. Loop ki jagah direct Rashi compare karo (Fast & Accurate)
    rashi_start = _sun_rashi_index(start_dt)
    rashi_end = _sun_rashi_index(end_dt)

    # Agar Rashi change hui hai toh True (Sankranti exists)
    # Agar Rashi same hai toh False (No Sankranti = Adhik Maas condition)
    return rashi_start != rashi_end


# ---------------------------------------------------------
# MAIN PUBLIC FUNCTION
# ---------------------------------------------------------

def detect_adhik_maas(year, lat, lon):
    """
    Returns list of Adhik Maas in given year by checking 
    Solar Ingress (Sankranti) between two consecutive Amavasya end times.
    """
    adhik_months = []

    # 1. Poore saal ki Amavasya ki details nikalna
    # Note: ensure karein ki _get_all_amavasya_of_year ab full objects return kare (jisme tithi_end ho)
    amavasya_data_list = []
    current_date = datetime(year, 1, 1).date()
    while current_date.year == year:
        hit = find_next_amavasya(current_date, lat, lon)
        if not hit or datetime.strptime(hit["date"], "%Y-%m-%d").year > year:
            break
        amavasya_data_list.append(hit)
        current_date = datetime.strptime(hit["date"], "%Y-%m-%d").date() + timedelta(days=1)

    # 2. Consecutive Amavasya ke beech Rashi check karna
    for i in range(len(amavasya_data_list) - 1):
        hit_start = amavasya_data_list[i]
        hit_end = amavasya_data_list[i + 1]

        # Exact transition times (Amavasya kab khatam hui)
        # Format assumed from your amavasya_details: "YYYY-MM-DD HH:MM"
        tithi_end_start = datetime.strptime(hit_start["tithi_end"], "%Y-%m-%d %H:%M")
        tithi_end_next = datetime.strptime(hit_end["tithi_end"], "%Y-%m-%d %H:%M")

        # Scientific Check: Amavasya khatam hone ke thik baad aur agli khatam hone ke thik pehle
        # Agar Sun ki Rashi nahi badli, matlab beech mein koi Sankranti nahi hui = Adhik Maas
        rashi_at_start = _sun_rashi_index(tithi_end_start + timedelta(minutes=5))
        rashi_at_next = _sun_rashi_index(tithi_end_next - timedelta(minutes=5))

        if rashi_at_start == rashi_at_next:
            # Ye confirm ho gaya ki ye mahina Adhik hai
            # Lunar month name nikalne ke liye get_lunar_month use karein
            month_info = get_lunar_month(tithi_end_start + timedelta(days=5)) # Middle of month check

            adhik_months.append({
                "year": year,
                "adhik_month": month_info["name"],
                "start_date": hit_start["date"],
                "end_date": hit_end["date"],
                "rashi_index": rashi_at_start
            })

    return adhik_months
