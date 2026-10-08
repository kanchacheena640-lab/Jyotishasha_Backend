"""
Kartik Chhath Puja engine (CHHATH-02).

Fully computed, year-independent -- there is NO yearly date table.

Observance algorithm (rule_version below):
  1. Lunar month: the nija (non-Adhik) Amanta Kartik lunation, i.e. the
     new-moon-to-new-moon lunation during which the sidereal Sun enters
     Vrischika. A lunation with no solar ingress is Adhik and is skipped.
  2. Sandhya Arghya day (D): the civil day at the Patna reference whose
     sunrise falls inside Kartik Shukla Shashthi (udaya tithi -- the
     convention Drik Panchang applies per location).
  3. Nahay Khay = D-2, Kharna = D-1, Usha Arghya = sunrise of D+1.
     These are counted from D, not from their own tithis (Drik 2023:
     Usha Arghya day had Ashtami at sunrise).
  4. Arghya times: sunset of D and sunrise of D+1 at the selected city.

The traditional rule is NOT fully resolved. Bihar observed 2025 on Oct 27
while udaya at Patna gives Oct 28 (Shashthi began 9 min after Patna
sunrise). Instead of overriding, the engine reports status
"needs_review" whenever any of these status flags is raised:
  kshaya, vriddhi, near_sunrise_boundary, reference_disagreement
  (udaya at the New Delhi cross-check reference picks another day),
  month_identification_uncertain.

Display policy (owner-approved, CHHATH-02C):
  * A successful response ALWAYS carries the four calculated ritual days,
    including when status is "needs_review". Dates are never blanked,
    suppressed or replaced by observed/curated dates.
  * `candidates` exposes the competing rules (Patna sunrise, New Delhi
    sunrise, Patna sunset) for transparency; only the Patna-sunrise
    candidate drives `days`.
  * status "confirmed" means the selected rule gave an unambiguous result
    with no review flag. It is an astronomical-calculation status, NOT a
    certification of regional observance (see `verification`).
  * Conventions applied without religious-policy sign-off are listed in
    rule.policy_unapproved: vriddhi -> earlier day, kshaya -> sunset
    fallback, 30-minute sunrise-boundary threshold.

Request contract (validated here, used by POST /api/festivals/chhath):
  year       JSON integer (not boolean) or a string of ASCII digits,
             MIN_YEAR..MAX_YEAR. Floats (even 2026.0) are rejected.
  city       key of CITIES. Mutually exclusive with latitude/longitude.
  latitude,  numbers (or numeric strings) inside India, both required
  longitude  when used; finite values only.
  language   "en" (default) or "hi": selects `name`, `weekday_local`,
             `location.name` and tithi `name`. Bilingual *_en/*_hi fields
             are always present; review_reasons are English only.
  type       "kartik" (default); Chaiti Chhath is not supported.

Proven-defect workaround (documented, see CHHATH-01):
  services/lunar_month_engine._find_amavasya_boundary samples once per day
  and can skip a short Amavasya; get_amanta_month therefore labels Kartik
  Shukla Shashthi 2023 (Patna) as "Margashirsha", and get_lunar_month is
  one month behind. This module finds new moons itself with a 6-hour step
  (a tithi always lasts more than 19 h, so no Amavasya can be skipped),
  reusing astro_core's tithi/longitude functions -- no new astronomy.
"""

import math
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from services.astro_core import _tithi_number_at, sidereal_longitudes
from services.panchang_engine import TITHI_NAMES, TITHI_NAMES_HI
from services.sun_calc import calculate_sunrise_sunset

RULE_VERSION = "chhath-kartik-udaya-patna-v1"
PRIMARY_RULE_ID = "patna_sunrise_udaya"
DELHI_RULE_ID = "delhi_sunrise_udaya"
SUNSET_RULE_ID = "patna_sunset_shashthi"
POLICY_STATUS = "owner_approved_display_policy"

SUPPORTED_LANGUAGES = ("en", "hi")
SUPPORTED_TYPES = ("kartik",)
IST = ZoneInfo("Asia/Kolkata")

MIN_YEAR = 2000
MAX_YEAR = 2100

KARTIK_INDEX = 7  # Chaitra = 0 ... Kartik = 7 (sun enters Vrischika, rashi 7)
SHASHTHI = 6

# Shashthi starting/ending this close to the reference sunrise means
# traditional Panchangs (different ephemerides) may pick another day.
BOUNDARY_MARGIN = timedelta(minutes=30)

INDIA_LAT_RANGE = (6.0, 37.5)
INDIA_LON_RANGE = (68.0, 97.5)

DEFAULT_CITY = "patna"
CROSS_CHECK_CITY = "delhi"

# Coordinates: city centre, decimal degrees. All Indian cities use IST.
CITIES = {
    "patna": {"name_en": "Patna", "name_hi": "पटना", "lat": 25.5941, "lon": 85.1376},
    "gaya": {"name_en": "Gaya", "name_hi": "गया", "lat": 24.7914, "lon": 85.0002},
    "muzaffarpur": {"name_en": "Muzaffarpur", "name_hi": "मुजफ्फरपुर", "lat": 26.1209, "lon": 85.3647},
    "bhagalpur": {"name_en": "Bhagalpur", "name_hi": "भागलपुर", "lat": 25.2425, "lon": 86.9842},
    "darbhanga": {"name_en": "Darbhanga", "name_hi": "दरभंगा", "lat": 26.1542, "lon": 85.8918},
    "ranchi": {"name_en": "Ranchi", "name_hi": "रांची", "lat": 23.3441, "lon": 85.3096},
    "jamshedpur": {"name_en": "Jamshedpur", "name_hi": "जमशेदपुर", "lat": 22.8046, "lon": 86.2029},
    "varanasi": {"name_en": "Varanasi", "name_hi": "वाराणसी", "lat": 25.3176, "lon": 82.9739},
    "gorakhpur": {"name_en": "Gorakhpur", "name_hi": "गोरखपुर", "lat": 26.7606, "lon": 83.3732},
    "prayagraj": {"name_en": "Prayagraj", "name_hi": "प्रयागराज", "lat": 25.4358, "lon": 81.8463},
    "lucknow": {"name_en": "Lucknow", "name_hi": "लखनऊ", "lat": 26.8467, "lon": 80.9462},
    "delhi": {"name_en": "New Delhi", "name_hi": "नई दिल्ली", "lat": 28.6139, "lon": 77.2090},
    "kolkata": {"name_en": "Kolkata", "name_hi": "कोलकाता", "lat": 22.5726, "lon": 88.3639},
    "mumbai": {"name_en": "Mumbai", "name_hi": "मुंबई", "lat": 19.0760, "lon": 72.8777},
    "pune": {"name_en": "Pune", "name_hi": "पुणे", "lat": 18.5204, "lon": 73.8567},
    "surat": {"name_en": "Surat", "name_hi": "सूरत", "lat": 21.1702, "lon": 72.8311},
    "ahmedabad": {"name_en": "Ahmedabad", "name_hi": "अहमदाबाद", "lat": 23.0225, "lon": 72.5714},
    "bengaluru": {"name_en": "Bengaluru", "name_hi": "बेंगलुरु", "lat": 12.9716, "lon": 77.5946},
    "hyderabad": {"name_en": "Hyderabad", "name_hi": "हैदराबाद", "lat": 17.3850, "lon": 78.4867},
    "chennai": {"name_en": "Chennai", "name_hi": "चेन्नई", "lat": 13.0827, "lon": 80.2707},
}

RITUAL_DAYS = [
    # (key, offset from Sandhya Arghya day, English, Hindi)
    ("nahay_khay", -2, "Nahay Khay", "नहाय खाय"),
    ("kharna", -1, "Kharna", "खरना"),
    ("sandhya_arghya", 0, "Sandhya Arghya", "संध्या अर्घ्य"),
    ("usha_arghya", 1, "Usha Arghya", "उषा अर्घ्य"),
]

STATUS_FLAGS = (
    "kshaya",
    "vriddhi",
    "near_sunrise_boundary",
    "reference_disagreement",
    "month_identification_uncertain",
)

WEEKDAYS_HI = {
    "Monday": "सोमवार", "Tuesday": "मंगलवार", "Wednesday": "बुधवार", "Thursday": "गुरुवार",
    "Friday": "शुक्रवार", "Saturday": "शनिवार", "Sunday": "रविवार",
}

HINDU_MONTHS = [
    "Chaitra", "Vaishakha", "Jyeshtha", "Ashadha", "Shravana", "Bhadrapada",
    "Ashwin", "Kartik", "Margashirsha", "Pausha", "Magha", "Phalguna",
]


class ChhathInputError(ValueError):
    """Invalid request input; carries a stable error code for the API."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class ChhathCalculationError(RuntimeError):
    """The observance could not be computed for the requested year."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


# -------------------------------------------------
# Location
# -------------------------------------------------
def _parse_coordinate(value, label):
    if isinstance(value, bool):
        raise ChhathInputError("INVALID_COORDINATES", f"{label} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ChhathInputError("INVALID_COORDINATES", f"{label} must be a number")
    if not math.isfinite(number):
        raise ChhathInputError("INVALID_COORDINATES", f"{label} must be a finite number")
    return number


def resolve_location(city=None, latitude=None, longitude=None):
    """City key, OR custom coordinates, OR (neither) Patna. Both together is rejected."""
    has_city = city is not None and city != ""
    has_coords = latitude is not None or longitude is not None
    if has_city and has_coords:
        raise ChhathInputError("CONFLICTING_LOCATION",
                               "Send either city or latitude/longitude, not both")

    if has_city:
        if not isinstance(city, str):
            raise ChhathInputError("INVALID_CITY", "City must be a string")
        key = city.strip().lower()
        if key not in CITIES:
            raise ChhathInputError("INVALID_CITY", f"Unsupported city: {city}")
        c = CITIES[key]
        return {"city": key, "name_en": c["name_en"], "name_hi": c["name_hi"],
                "lat": c["lat"], "lon": c["lon"], "tz": "Asia/Kolkata"}

    if not has_coords:
        return resolve_location(DEFAULT_CITY)
    if latitude is None or longitude is None:
        raise ChhathInputError("INVALID_COORDINATES", "Both latitude and longitude are required")
    lat = _parse_coordinate(latitude, "Latitude")
    lon = _parse_coordinate(longitude, "Longitude")
    if not (INDIA_LAT_RANGE[0] <= lat <= INDIA_LAT_RANGE[1]
            and INDIA_LON_RANGE[0] <= lon <= INDIA_LON_RANGE[1]):
        raise ChhathInputError("INVALID_COORDINATES", "Coordinates must be within India")
    return {"city": "custom", "name_en": "Custom location", "name_hi": "चयनित स्थान",
            "lat": lat, "lon": lon, "tz": "Asia/Kolkata"}


def validate_year(year):
    """JSON integer (not bool) or ASCII-digit string; floats are always rejected."""
    if isinstance(year, bool):
        raise ChhathInputError("INVALID_YEAR", "Year must be an integer")
    if isinstance(year, int):
        y = year
    elif isinstance(year, str) and re.fullmatch(r"[0-9]{1,4}", year.strip()):
        y = int(year.strip())
    else:
        raise ChhathInputError("INVALID_YEAR", "Year must be an integer")
    if not (MIN_YEAR <= y <= MAX_YEAR):
        raise ChhathInputError("INVALID_YEAR", f"Year must be between {MIN_YEAR} and {MAX_YEAR}")
    return y


def validate_language(language):
    if language is None:
        return "en"
    if not isinstance(language, str) or language.strip().lower() not in SUPPORTED_LANGUAGES:
        raise ChhathInputError("INVALID_LANGUAGE", "Language must be 'en' or 'hi'")
    return language.strip().lower()


def validate_type(festival_type):
    if festival_type is None:
        return "kartik"
    if not isinstance(festival_type, str) or festival_type.strip().lower() not in SUPPORTED_TYPES:
        raise ChhathInputError("INVALID_TYPE", "Only Kartik Chhath is supported")
    return festival_type.strip().lower()


def current_ist_year():
    """Default request year, taken from Asia/Kolkata (not server-local time)."""
    return datetime.now(IST).year


# -------------------------------------------------
# Astronomy helpers (reuse astro_core / sun_calc)
# -------------------------------------------------
def _naive(dt):
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def _sun_times(d, lat, lon):
    sr, ss = calculate_sunrise_sunset(d, lat, lon)
    if sr is None or ss is None:
        raise ChhathCalculationError("SUN_TIMES_UNAVAILABLE", f"Sunrise/sunset unavailable for {d}")
    return _naive(sr), _naive(ss)


def _sun_rashi(dt_ist):
    sun, _ = sidereal_longitudes(dt_ist)
    return int(sun // 30) % 12


def _bisect(lo, hi, is_after):
    """Smallest time in (lo, hi] where is_after(t) is True, to 1-second precision."""
    while hi - lo > timedelta(seconds=1):
        mid = lo + (hi - lo) / 2
        if is_after(mid):
            hi = mid
        else:
            lo = mid
    return hi.replace(microsecond=0)


def find_new_moons(start, end, step=timedelta(hours=6)):
    """New-moon instants (Amavasya -> Shukla Pratipada) in [start, end]."""
    moons = []
    t0, prev = start, _tithi_number_at(start)
    while t0 < end:
        t1 = t0 + step
        cur = _tithi_number_at(t1)
        if prev == 30 and cur != 30:
            moons.append(_bisect(t0, t1, lambda t: _tithi_number_at(t) != 30))
        t0, prev = t1, cur
    return moons


def classify_lunation(rashi_start, rashi_end):
    """Amanta month of a lunation from the Sun's sidereal rashi at both new moons.

    Month index = rashi the Sun enters during the lunation (Chaitra=Mesha=0).
    No ingress -> Adhik month, named after the following nija month.
    Two ingresses -> Kshaya-masa lunation (covers two month names).
    """
    span = (rashi_end - rashi_start) % 12
    if span == 0:
        return {"index": (rashi_start + 1) % 12, "is_adhik": True, "is_kshaya_masa": False,
                "indices": [(rashi_start + 1) % 12]}
    if span == 1:
        return {"index": rashi_end, "is_adhik": False, "is_kshaya_masa": False,
                "indices": [rashi_end]}
    return {"index": rashi_end, "is_adhik": False, "is_kshaya_masa": True,
            "indices": [(rashi_start + k) % 12 for k in range(1, span + 1)]}


def select_kartik_lunation(lunations):
    """Pick the nija Kartik lunation.

    `lunations` is a list of dicts {start, end, rashi_start, rashi_end}.
    Returns (lunation, info) where info records whether an Adhik Kartik was
    skipped and whether identification is uncertain (kshaya-masa / missing).
    """
    adhik_skipped = False
    for lun in lunations:
        cls = classify_lunation(lun["rashi_start"], lun["rashi_end"])
        if KARTIK_INDEX not in cls["indices"]:
            continue
        if cls["is_adhik"]:
            adhik_skipped = True
            continue
        return lun, {"is_adhik": False, "adhik_kartik_skipped": adhik_skipped,
                     "is_kshaya_masa": cls["is_kshaya_masa"]}
    return None, {"is_adhik": False, "adhik_kartik_skipped": adhik_skipped, "is_kshaya_masa": False}


def _lunations_for_year(year):
    moons = find_new_moons(datetime(year, 9, 1), datetime(year, 12, 31))
    return [
        {"start": a, "end": b,
         "rashi_start": _sun_rashi(a + timedelta(minutes=1)),
         "rashi_end": _sun_rashi(b - timedelta(minutes=1))}
        for a, b in zip(moons, moons[1:])
    ]


def find_tithi_window(new_moon, tithi, step=timedelta(hours=1)):
    """[start, end) of the given Shukla tithi following `new_moon`."""
    t = new_moon
    limit = new_moon + timedelta(days=tithi + 2)
    while _tithi_number_at(t + step) != tithi:
        t += step
        if t > limit:
            raise ChhathCalculationError("TITHI_NOT_FOUND", "Shashthi not found after new moon")
    start = _bisect(t, t + step, lambda x: _tithi_number_at(x) == tithi)
    t = start
    while _tithi_number_at(t + step) == tithi:
        t += step
    end = _bisect(t, t + step, lambda x: _tithi_number_at(x) != tithi)
    return start, end


def udaya_days(window_start, window_end, lat, lon):
    """Civil days whose local sunrise falls inside [window_start, window_end)."""
    days = []
    d = window_start.date() - timedelta(days=1)
    while d <= window_end.date():
        sr, _ = _sun_times(d, lat, lon)
        if window_start <= sr < window_end:
            days.append(d)
        d += timedelta(days=1)
    return days


def sunset_day(window_start, window_end, lat, lon):
    """Informational: first civil day whose sunset falls inside the window."""
    d = window_start.date()
    while d <= window_end.date():
        _, ss = _sun_times(d, lat, lon)
        if window_start <= ss < window_end:
            return d
        d += timedelta(days=1)
    return None


def _tithi_info(dt_ist):
    n = _tithi_number_at(dt_ist)
    return {"number": n, "paksha": "Shukla" if n <= 15 else "Krishna",
            "name_en": TITHI_NAMES[n - 1], "name_hi": TITHI_NAMES_HI[n - 1]}


def _fmt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M")


def _ritual_dates(anchor):
    if anchor is None:
        return None
    return {key: (anchor + timedelta(days=offset)).isoformat() for key, offset, _, _ in RITUAL_DAYS}


def _candidate(rule_id, label, reference_city, event, anchor, matching_days, is_primary):
    return {
        "rule_id": rule_id,
        "label": label,
        "reference_city": reference_city,
        "evaluated_at": event,
        "is_primary": is_primary,
        "sandhya_arghya": anchor.isoformat() if anchor else None,
        "matching_days": [d.isoformat() for d in matching_days],
        "dates": _ritual_dates(anchor),
    }


# -------------------------------------------------
# Main entry point
# -------------------------------------------------
def calculate_chhath(year, city=None, latitude=None, longitude=None, language=None, festival_type=None):
    year = validate_year(year)
    location = resolve_location(city, latitude, longitude)
    language = validate_language(language)
    festival_type = validate_type(festival_type)
    ref = resolve_location(DEFAULT_CITY)
    cross = resolve_location(CROSS_CHECK_CITY)

    lunation, month_info = select_kartik_lunation(_lunations_for_year(year))
    if lunation is None:
        raise ChhathCalculationError("KARTIK_NOT_FOUND", f"Kartik lunation not found for {year}")

    sh_start, sh_end = find_tithi_window(lunation["start"], SHASHTHI)
    reasons = []

    # --- Reference (Patna) udaya selection ---
    ref_days = udaya_days(sh_start, sh_end, ref["lat"], ref["lon"])
    kshaya = len(ref_days) == 0
    vriddhi = len(ref_days) > 1
    if ref_days:
        anchor = ref_days[0]
        anchor_basis = "udaya_reference"
    else:
        # No Patna sunrise inside Shashthi. Traditional resolution is not
        # established; present the day on which Shashthi prevails at sunset
        # as a candidate only (status forced to needs_review).
        anchor = sunset_day(sh_start, sh_end, ref["lat"], ref["lon"]) or sh_start.date()
        anchor_basis = "kshaya_candidate_sunset"
    if kshaya:
        reasons.append("Shashthi does not prevail at any Patna sunrise (kshaya).")
    if vriddhi:
        reasons.append("Shashthi prevails at two Patna sunrises (vriddhi); earlier day shown.")

    # --- Sunrise-boundary sensitivity at the reference ---
    near_boundary = False
    for edge in (sh_start, sh_end):
        sr, _ = _sun_times(edge.date(), ref["lat"], ref["lon"])
        if abs(edge - sr) < BOUNDARY_MARGIN:
            near_boundary = True
    if near_boundary:
        reasons.append("Shashthi begins or ends within 30 minutes of Patna sunrise; "
                       "published Panchangs may differ.")

    # --- Cross-check reference (New Delhi, Drik default location) ---
    cross_days = udaya_days(sh_start, sh_end, cross["lat"], cross["lon"])
    cross_anchor = cross_days[0] if cross_days else None
    reference_disagreement = cross_anchor != anchor
    if reference_disagreement:
        reasons.append("Udaya rule at the New Delhi cross-check reference selects a different day.")

    month_uncertain = month_info["is_kshaya_masa"]
    if month_uncertain:
        reasons.append("Kartik falls in a kshaya-masa lunation.")

    # --- Selected-city information (does not change the dates) ---
    city_days = udaya_days(sh_start, sh_end, location["lat"], location["lon"])
    city_anchor = city_days[0] if city_days else None
    ref_sunset_day = sunset_day(sh_start, sh_end, ref["lat"], ref["lon"])

    flags = {
        "kshaya": kshaya,
        "vriddhi": vriddhi,
        "near_sunrise_boundary": near_boundary,
        "reference_disagreement": reference_disagreement,
        "month_identification_uncertain": month_uncertain,
        # informational only
        "adhik_kartik_skipped": month_info["adhik_kartik_skipped"],
        "date_differs_by_city": city_anchor != anchor,
        "sunset_rule_differs": ref_sunset_day != anchor,
    }
    status = "needs_review" if any(flags[k] for k in STATUS_FLAGS) else "confirmed"

    days = []
    for key, offset, name_en, name_hi in RITUAL_DAYS:
        d = anchor + timedelta(days=offset)
        sr, ss = _sun_times(d, location["lat"], location["lon"])
        weekday = d.strftime("%A")
        tithi = _tithi_info(sr)
        tithi["name"] = tithi["name_hi"] if language == "hi" else tithi["name_en"]
        item = {
            "key": key, "name_en": name_en, "name_hi": name_hi,
            "name": name_hi if language == "hi" else name_en,
            "date": d.isoformat(), "weekday": weekday,
            "weekday_local": WEEKDAYS_HI[weekday] if language == "hi" else weekday,
            "sunrise": sr.strftime("%H:%M"), "sunset": ss.strftime("%H:%M"),
            "tithi_at_sunrise": tithi,
        }
        if key == "sandhya_arghya":
            item["arghya_time"] = ss.strftime("%H:%M")
            item["arghya_event"] = "sunset"
        elif key == "usha_arghya":
            item["arghya_time"] = sr.strftime("%H:%M")
            item["arghya_event"] = "sunrise"
        days.append(item)

    policy_unapproved = []
    if vriddhi:
        policy_unapproved.append("vriddhi_earlier_day")
    if kshaya:
        policy_unapproved.append("kshaya_sunset_fallback")
    if near_boundary:
        policy_unapproved.append("near_sunrise_boundary_threshold_30min")

    candidates = [
        _candidate(PRIMARY_RULE_ID, "Shashthi at sunrise, Patna reference (primary)",
                   DEFAULT_CITY, "sunrise", anchor, ref_days, True),
        _candidate(DELHI_RULE_ID, "Shashthi at sunrise, New Delhi cross-check",
                   CROSS_CHECK_CITY, "sunrise", cross_anchor, cross_days, False),
        _candidate(SUNSET_RULE_ID, "Shashthi at sunset, Patna reference",
                   DEFAULT_CITY, "sunset", ref_sunset_day,
                   [ref_sunset_day] if ref_sunset_day else [], False),
    ]

    location = dict(location, name=location["name_hi"] if language == "hi" else location["name_en"])

    return {
        "festival": "chhath",
        "type": festival_type,
        "language": language,
        "year": year,
        "status": status,
        "source": "computed",
        "rule_version": RULE_VERSION,
        "rule": {
            "sandhya_arghya": "Kartik Shukla Shashthi prevailing at sunrise (udaya) at the Patna reference",
            "anchor_basis": anchor_basis,
            "reference_city": DEFAULT_CITY,
            "cross_check_city": CROSS_CHECK_CITY,
            "offsets": {"nahay_khay": -2, "kharna": -1, "sandhya_arghya": 0, "usha_arghya": 1},
            "rule_id": PRIMARY_RULE_ID,
            "rule_version": RULE_VERSION,
            "calculation_basis": "astronomical: Lahiri sidereal tithi (Swiss Ephemeris) "
                                 "at Astral sunrise, IST",
            "reference_location": {"city": ref["city"], "name_en": ref["name_en"],
                                   "lat": ref["lat"], "lon": ref["lon"]},
            "policy_status": POLICY_STATUS,
            "policy_unapproved": policy_unapproved,
        },
        "verification": {
            "status_scope": "astronomical_calculation_under_selected_rule",
            "regional_observance_verified": False,
            "note": "status 'confirmed' means the Patna sunrise rule gave an unambiguous date "
                    "with no review flag; it does not certify that every regional Panchang "
                    "or community observes the same date.",
        },
        "location": location,
        "timezone_display": "IST",
        "lunar_month": {
            "amanta": HINDU_MONTHS[KARTIK_INDEX],
            "paksha": "Shukla",
            "is_adhik": False,
            "adhik_kartik_skipped": month_info["adhik_kartik_skipped"],
            "new_moon_ist": _fmt(lunation["start"]),
        },
        "shashthi": {"start_ist": _fmt(sh_start), "end_ist": _fmt(sh_end)},
        "days": days,
        "flags": flags,
        "review_reasons": reasons,
        "candidates": candidates,
        "diagnostics": {
            "reference_udaya_days": [d.isoformat() for d in ref_days],
            "cross_check_udaya_days": [d.isoformat() for d in cross_days],
            "selected_city_udaya_days": [d.isoformat() for d in city_days],
            "reference_sunset_rule_day": ref_sunset_day.isoformat() if ref_sunset_day else None,
        },
    }
