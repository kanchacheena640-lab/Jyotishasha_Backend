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

    # OLD SIGNATURE
    res, tret = swe.rise_trans(
        jd_ut,
        swe.MOON,
        None,
        rsmi,
        (lon, lat, 0)
    )

    if res != 0 or not tret or tret[0] <= 0:
        return None

    jd_rise = tret[0]

    y, mo, d, ut = swe.revjul(jd_rise)

    if ut is None:
        return None

    h = int(ut)
    m = int((ut - h) * 60)
    s = int((((ut - h) * 60) - m) * 60)

    utc_dt = datetime(y, mo, d, h, m, s)

    return utc_dt + timedelta(hours=tz_offset)
