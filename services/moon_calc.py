import swisseph as swe
from datetime import datetime, timedelta

def get_moonrise(date_obj, lat, lon, tz_offset=5.5):

    jd_ut = swe.julday(
        date_obj.year,
        date_obj.month,
        date_obj.day,
        0.0
    )

    rsmi = swe.CALC_RISE

    res, tret = swe.rise_trans(
        jd_ut,
        swe.MOON,
        None,
        rsmi,
        (lon, lat, 0)
    )

    if res != 0:
        return None

    jd_rise = tret[0]

    y, mo, d, ut = swe.revjul(jd_rise)

    ut_sec = round(ut * 3600)
    h = ut_sec // 3600
    m = (ut_sec % 3600) // 60
    s = ut_sec % 60

    utc_dt = datetime(y, mo, d, h, m, s)

    return utc_dt + timedelta(hours=tz_offset)
