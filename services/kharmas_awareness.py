"""Kharmas AWARENESS for Muhurat results -- a post-calculation annotation layer.

Product rule: Kharmas never restricts anything. The Muhurat engine selects,
scores, ranks and explains dates exactly as before; this module only attaches
additional metadata to the items that engine already returned:

  * marriage, grah_pravesh -> level "badge"  (badge label "Kharmas" / "खरमास")
  * naamkaran              -> level "info"   (informational advisory, no badge)
  * every other activity   -> untouched (no new keys at all)

It never changes dates, order, scores, reasons or any other existing field, and
never mutates its input: it deep-copies the results, builds the complete
annotated copy, and only then returns it. Callers keep the original response if
anything raises.

Overlap is evaluated per Hindu day: local sunrise on the item's date to local
sunrise on the next date (services.sun_calc, the same helper the Panchang uses),
against the exact Kharmas interval [start ingress, end ingress) from
services.kharmas_engine.
  * full    -- the whole Hindu day lies inside Kharmas
  * partial -- the Kharmas start or end ingress falls inside the Hindu day
Where the sunrise model is not supported (outside
kharmas_engine.OBSERVANCE_LAT_RANGE / OBSERVANCE_LON_RANGE) or sunrise cannot be
computed, the IST calendar day (00:00-24:00 IST) of the item's date is used and
reported as basis "ist_calendar_day".
"""

import copy
from datetime import date, datetime, time, timedelta

from lahiri_mode import ensure_lahiri_mode
from services.kharmas_engine import (
    IST,
    KHARMAS_NAMES,
    SANKRANTI_NAMES,
    get_kharmas_intervals,
    observance_supported,
)
from services.sankranti_engine import RASHI_NAMES_EN, RASHI_NAMES_HI
from services.sun_calc import calculate_sunrise_sunset

POLICY = {
    "marriage": "badge",
    "grah_pravesh": "badge",
    "naamkaran": "info",
}
BADGE_LABEL = {"en": "Kharmas", "hi": "खरमास"}
BASIS_SUNRISE = "sunrise_to_sunrise"
BASIS_CALENDAR = "ist_calendar_day"

EN_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
HI_MONTHS = ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"]

ACTIVITY_SENTENCE = {
    "en": {
        "marriage": "Observance of Kharmas for weddings varies by tradition and family. "
                    "Please follow your family tradition or consult your priest.",
        "grah_pravesh": "Observance of Kharmas for Griha Pravesh (housewarming) varies by tradition and family. "
                        "Please follow your family tradition or consult your priest.",
        "naamkaran": "For information only: practice regarding Naamkaran during Kharmas varies by tradition and family.",
    },
    "hi": {
        "marriage": "विवाह के लिए खरमास का पालन परंपरा और परिवार के अनुसार अलग-अलग होता है। "
                    "कृपया अपनी पारिवारिक परंपरा का पालन करें या अपने पुरोहित से परामर्श लें।",
        "grah_pravesh": "गृह प्रवेश के लिए खरमास का पालन परंपरा और परिवार के अनुसार अलग-अलग होता है। "
                        "कृपया अपनी पारिवारिक परंपरा का पालन करें या अपने पुरोहित से परामर्श लें।",
        "naamkaran": "केवल जानकारी हेतु: खरमास में नामकरण से जुड़ी प्रथा परंपरा और परिवार के अनुसार अलग-अलग होती है।",
    },
}


def normalise_activity(activity):
    """Same normalisation the Muhurat engine applies to load rules."""
    if not isinstance(activity, str):
        return None
    return activity.replace("-", "_").replace(" ", "_")


def awareness_level(activity):
    return POLICY.get(normalise_activity(activity))


# ----------------------------------------------------------------------------
# Formatting
# ----------------------------------------------------------------------------

def _d(d, lang):
    return f"{d.day} {HI_MONTHS[d.month - 1]} {d.year}" if lang == "hi" else f"{d.day} {EN_MONTHS[d.month - 1]} {d.year}"


def _dt(dt, lang):
    dt = dt.astimezone(IST)
    if lang == "hi":
        return f"{_d(dt.date(), lang)}, {dt:%H:%M}"
    return f"{_d(dt.date(), lang)}, {dt.strftime('%I:%M %p').lstrip('0')}"


def _iso(dt):
    return dt.astimezone(IST).isoformat(timespec="seconds")


def _period_name(p, lang):
    sign = (RASHI_NAMES_HI if lang == "hi" else RASHI_NAMES_EN)[p["start_sign"]]
    name = KHARMAS_NAMES[lang][p["kind"]]
    return f"{name} (सूर्य {sign} राशि में)" if lang == "hi" else f"{name} (Sun in {sign})"


def _period_span(p, lang):
    if lang == "hi":
        return f"{_dt(p['start'], lang)} से {_dt(p['end'], lang)} IST तक"
    return f"{_dt(p['start'], lang)} to {_dt(p['end'], lang)} IST"


def _day_phrase(civil_date, window, lang):
    """Names the evaluated day explicitly -- never relative wording."""
    ws, we, basis = window
    if basis == BASIS_CALENDAR:
        if lang == "hi":
            return (f"IST कैलेंडर दिन {_d(civil_date, lang)} (00:00–24:00 IST; इस स्थान के लिए "
                    f"सूर्योदय-आधारित हिंदू दिन उपलब्ध नहीं)")
        return (f"the IST calendar day {_d(civil_date, lang)} (00:00–24:00 IST; a sunrise-based "
                f"Hindu day is not available for this location)")
    if lang == "hi":
        return f"{_d(civil_date, lang)} का हिंदू दिन (सूर्योदय {_dt(ws, lang)} से अगले सूर्योदय {_dt(we, lang)} IST तक)"
    return f"the Hindu day of {_d(civil_date, lang)} (sunrise {_dt(ws, lang)} to next sunrise {_dt(we, lang)} IST)"


def _advisory(activity, p, overlap, boundary, civil_date, window, lang):
    day = _day_phrase(civil_date, window, lang)
    act = ACTIVITY_SENTENCE[lang][activity]
    name, span = _period_name(p, lang), _period_span(p, lang)
    if overlap == "full":
        if lang == "hi":
            return f"{day} पूरी तरह {name} के भीतर है ({span})। {act}"
        return f"{day[0].upper()}{day[1:]} falls entirely within {name}, {span}. {act}"
    sank = SANKRANTI_NAMES[lang][boundary["sign"]]
    at = _dt(boundary["dt"], lang)
    if boundary["type"] == "starts":
        if lang == "hi":
            return f"{day} में खरमास शुरू होता है: {sank} {at} IST पर। {name} {_dt(p['end'], lang)} IST तक रहेगा। {act}"
        return f"Kharmas begins within {day}: {sank} is at {at} IST. {name} lasts until {_dt(p['end'], lang)} IST. {act}"
    if lang == "hi":
        return f"{day} में खरमास समाप्त होता है: {sank} {at} IST पर। {name} {_dt(p['start'], lang)} IST से चल रहा था। {act}"
    return f"Kharmas ends within {day}: {sank} is at {at} IST. {name} began on {_dt(p['start'], lang)} IST. {act}"


# ----------------------------------------------------------------------------
# Day windows and overlap
# ----------------------------------------------------------------------------

def _calendar_window(d):
    start = datetime.combine(d, time.min, tzinfo=IST)
    return start, start + timedelta(days=1), BASIS_CALENDAR


def _day_window(d, lat, lon, sunrise_ok):
    """(start, end, basis) of the day evaluated for civil date d."""
    if sunrise_ok:
        sr, _ = calculate_sunrise_sunset(d, lat, lon)
        sr_next, _ = calculate_sunrise_sunset(d + timedelta(days=1), lat, lon)
        if sr is not None and sr_next is not None and sr < sr_next:
            return sr.astimezone(IST), sr_next.astimezone(IST), BASIS_SUNRISE
    return _calendar_window(d)


def _classify(intervals, window):
    """(period, overlap, boundary) or None for the first overlapping period."""
    ws, we, _ = window
    for p in intervals:
        if p["start"] < we and p["end"] > ws:
            if p["start"] <= ws and p["end"] >= we:
                return p, "full", None
            if ws < p["start"] < we:
                return p, "partial", {"type": "starts", "dt": p["start"], "sign": p["start_sign"]}
            return p, "partial", {"type": "ends", "dt": p["end"], "sign": p["end_sign"]}
    return None


def _period_public(p, lang):
    return {"id": p["id"], "kind": p["kind"], "name": KHARMAS_NAMES[lang][p["kind"]],
            "start": _iso(p["start"]), "end": _iso(p["end"])}


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------

def annotate_muhurat_results(activity, results, lat, lon, language, window_start, window_end):
    """Return (annotated_results, awareness) for an awareness activity, or None
    for any other activity. `results` is never modified; the returned list is a
    deep copy in the SAME order with an extra "kharmas" key on overlapping items.
    `window_start`/`window_end` (dates, end exclusive) are the request window
    used for the top-level summary."""
    act = normalise_activity(activity)
    level = POLICY.get(act)
    if level is None:
        return None
    ensure_lahiri_mode()
    lang = "hi" if language == "hi" else "en"
    lat, lon = float(lat), float(lon)
    sunrise_ok = observance_supported(lat, lon)

    out = copy.deepcopy(list(results))
    item_dates = [date.fromisoformat(str(x["date"])[:10]) for x in out]
    lo = min(item_dates + [window_start]) - timedelta(days=1)
    hi = max(item_dates + [window_end]) + timedelta(days=2)
    intervals = get_kharmas_intervals(datetime.combine(lo, time.min, tzinfo=IST),
                                      datetime.combine(hi, time.min, tzinfo=IST))

    for item, d in zip(out, item_dates):
        # Fast reject: the evaluated day always lies within [d 00:00, d+2 00:00) IST.
        coarse = (datetime.combine(d, time.min, tzinfo=IST), datetime.combine(d + timedelta(days=2), time.min, tzinfo=IST))
        if not any(p["start"] < coarse[1] and p["end"] > coarse[0] for p in intervals):
            continue
        window = _day_window(d, lat, lon, sunrise_ok)
        hit = _classify(intervals, window)
        if hit is None:
            continue
        p, overlap, boundary = hit
        meta = {
            "overlap": overlap,
            "level": level,
            "period": _period_public(p, lang),
            "boundary": None if boundary is None else {
                "type": boundary["type"],
                "ingress": _iso(boundary["dt"]),
                "ingress_civil_date": boundary["dt"].astimezone(IST).date().isoformat(),
                "sankranti": SANKRANTI_NAMES[lang][boundary["sign"]],
            },
            "day_window": {
                "civil_date": d.isoformat(),
                "basis": window[2],
                "start": _iso(window[0]),
                "end": _iso(window[1]),
            },
            "advisory": _advisory(act, p, overlap, boundary, d, window, lang),
        }
        if level == "badge":
            meta["badge"] = {"label": BADGE_LABEL[lang]}
        item["kharmas"] = meta

    w0 = datetime.combine(window_start, time.min, tzinfo=IST)
    w1 = datetime.combine(window_end, time.min, tzinfo=IST)
    periods = [p for p in intervals if p["start"] < w1 and p["end"] > w0]
    if periods:
        spans = "; ".join(f"{_period_name(p, lang)}: {_period_span(p, lang)}" for p in periods)
        if lang == "hi":
            notice = (f"इस अवधि में खरमास: {spans}। तिथियाँ यथावत गणना के अनुसार दिखाई गई हैं; "
                      f"खरमास में आने वाली तिथियाँ चिह्नित हैं। {ACTIVITY_SENTENCE[lang][act]}")
        else:
            notice = (f"Kharmas in this period: {spans}. Dates are shown exactly as calculated; "
                      f"dates within Kharmas are marked. {ACTIVITY_SENTENCE[lang][act]}")
    else:
        notice = None
    awareness = {
        "level": level,
        "badge_label": BADGE_LABEL[lang] if level == "badge" else None,
        "window": {"start": window_start.isoformat(), "end_exclusive": window_end.isoformat()},
        "periods": [_period_public(p, lang) for p in periods],
        "notice": notice,
        "day_basis": BASIS_SUNRISE if sunrise_ok else BASIS_CALENDAR,
        "method": "Hindu day = local sunrise to next sunrise (IST calendar day where sunrise is unavailable); "
                  "Kharmas = Sun (sidereal Lahiri) in Dhanu or Meena, [start ingress, end ingress); "
                  "awareness only -- dates, scores and order are unchanged",
    }
    return out, awareness
