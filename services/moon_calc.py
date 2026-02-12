import swisseph as swe
from datetime import datetime, timedelta


def get_moonrise(date_obj, lat, lon, tz_offset=5.5):
    try:
        # 🔹 Julian Day at 00:00 UT
        jd_ut = swe.julday(
            date_obj.year,
            date_obj.month,
            date_obj.day,
            0.0
        )

        rsmi = swe.CALC_RISE

        # 🔹 Try old signature first
        try:
            result = swe.rise_trans(
                jd_ut,
                swe.MOON,
                None,
                rsmi,
                (lon, lat, 0)
            )
        except TypeError:
            # 🔹 Fallback to extended signature (newer versions)
            result = swe.rise_trans(
                jd_ut,
                swe.MOON,
                None,
                swe.FLG_SWIEPH,
                rsmi,
                (lon, lat, 0),
                1013.25,
                15.0
            )

        if not result:
            return None

        # 🔹 Handle different return formats
        if isinstance(result, tuple):
            if len(result) == 2:
                res, tret = result
            elif len(result) >= 3:
                res, tret = result[0], result[1]
            else:
                return None
        else:
            return None

        if res != 0 or not tret or tret[0] <= 0:
            return None

        jd_rise = tret[0]

        rev = swe.revjul(jd_rise)
        if not rev or len(rev) < 4:
            return None

        y, mo, d, ut = rev

        if ut is None:
            return None

        # 🔹 Convert decimal hours safely
        h = int(ut)
        m = int((ut - h) * 60)
        s = int(round((((ut - h) * 60) - m) * 60))

        utc_dt = datetime(y, mo, d, h, m, s)

        # 🔹 Convert to IST (default)
        return utc_dt + timedelta(hours=tz_offset)

    except Exception as e:
        print("Moonrise calculation error:", e)
        return None
