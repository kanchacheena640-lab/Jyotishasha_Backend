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
    check_date = start_date

    while check_date < end_date:
        sankranti = get_sankranti_details(check_date, lat, lon)
        if sankranti:
            return True
        check_date += timedelta(days=1)

    return False


# ---------------------------------------------------------
# MAIN PUBLIC FUNCTION
# ---------------------------------------------------------

def detect_adhik_maas(year, lat, lon):
    """
    Returns list of Adhik Maas in given year.
    """

    adhik_months = []

    amavasya_dates = _get_all_amavasya_of_year(year, lat, lon)

    for i in range(len(amavasya_dates) - 1):

        start_amavasya = amavasya_dates[i]
        end_amavasya = amavasya_dates[i + 1]

        start_dt = datetime.combine(start_amavasya, datetime.min.time()).replace(hour=12)
        end_dt = datetime.combine(end_amavasya, datetime.min.time()).replace(hour=12)

        rashi_start = _sun_rashi_index(start_dt)
        rashi_end = _sun_rashi_index(end_dt)

        if rashi_start == rashi_end:

            lunar_month = get_lunar_month(start_dt)

            adhik_months.append({
                "year": year,
                "adhik_month": lunar_month,
                "start_date": start_amavasya.strftime("%Y-%m-%d"),
                "end_date": end_amavasya.strftime("%Y-%m-%d"),
            })

    return adhik_months
