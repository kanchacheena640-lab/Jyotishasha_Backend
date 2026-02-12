import swisseph as swe
from datetime import datetime, timedelta

def get_moonrise(date_obj, lat, lon, tz_offset=5.5):

    swe.set_sid_mode(swe.SIDM_LAHIRI)
    swe.set_topo(lon, lat, 0)

    jd_start = swe.julday(date_obj.year, date_obj.month, date_obj.day, 0.0)

    res, tret = swe.rise_trans(
        jd_start,
        swe.MOON,
        lon,
        lat,
        swe.CALC_RISE
    )

    if res != 0:
        return None

    jd_rise = tret[0]

    y, m, d, ut = swe.revjul(jd_rise)

    hour = int(ut)
    minute = int((ut - hour) * 60)

    utc_dt = datetime(y, m, d, hour, minute)

    return utc_dt + timedelta(hours=tz_offset)

