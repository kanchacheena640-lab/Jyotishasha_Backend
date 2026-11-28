import traceback
from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from services.panchang_engine import calculate_panchang
from services.adhik_maas_engine import detect_adhik_maas
from services.astro_core import _tithi_number_at
from services.pradosh_engine import (
    DEFAULT_LATITUDE as PRADOSH_DEFAULT_LATITUDE,
    DEFAULT_LONGITUDE as PRADOSH_DEFAULT_LONGITUDE,
    PradoshInputError,
    convention as pradosh_convention,
    get_pradosh_calendar,
    get_pradosh_today_next,
    ist_today as pradosh_ist_today,
    normalise_language,
    normalise_location,
    validate_year as pradosh_validate_year,
)
from services.events_engine import (
    find_next_pradosh,
    get_sankashti_details,       
    find_next_sankashti,    
    get_amavasya_details,
    find_next_amavasya,
    get_purnima_details,
    find_next_purnima,
    get_vinayaka_chaturthi_details,
    find_next_vinayaka_chaturthi,
    get_shivratri_details,
    find_next_shivratri,
)
from services.sankranti_engine import (
    get_sankranti_details,
    find_next_sankranti
)
from services.kharmas_engine import (
    AS_OF_MAX_YEAR,
    AS_OF_MIN_YEAR,
    DEFAULT_LATITUDE,
    DEFAULT_LONGITUDE,
    IST,
    MAX_YEAR,
    MIN_YEAR,
    OBSERVANCE_LAT_RANGE,
    OBSERVANCE_LON_RANGE,
    SEARCH_RESOLUTION_SECONDS,
    KharmasInputError,
    ephemeris_for_year,
    get_kharmas_periods,
    get_kharmas_status,
    observance_supported,
)


def _round_coord_for_meta(value, default):
    # Only reached after get_kharmas_status() validated the coordinates.
    return round(float(default if value is None else value), 2)

routes_events = Blueprint("routes_events", __name__)


def _pradosh_body():
    """JSON body as a dict (empty body -> {}); anything else that is not a JSON object -> 400."""
    raw = request.get_data(cache=True)
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise PradoshInputError("request body must be valid JSON")
    if not isinstance(data, dict):
        raise PradoshInputError("request body must be a JSON object")
    return data


def _pradosh_legacy(record, language):
    """A resolved Pradosh record in the pre-existing {today,next} item shape
    (type/name_en/name_hi/slug/date/paksha/sunset_time/tithi_at_sunset, unchanged
    names and formats), plus additive fields."""
    if record is None:
        return None
    sunset = datetime.fromisoformat(record["sunset"]).replace(tzinfo=None)
    sunset_minute = sunset.replace(second=0, microsecond=0)   # legacy sunset_time is HH:MM
    paksha = record["paksha"]
    item = {
        # --- legacy fields (same keys, same value formats as before) ---
        "type": "pradosh",
        "name_en": f"{paksha['en']} Pradosh Vrat",
        "name_hi": f"{paksha['hi']} प्रदोष व्रत",
        "slug": "pradosh-vrat",
        "date": record["date"],
        "paksha": paksha["en"],
        "sunset_time": sunset_minute.strftime("%H:%M"),
        "tithi_at_sunset": _tithi_number_at(sunset_minute),
    }
    item.update(_pradosh_additive(record, language))
    return item


def _pradosh_additive(record, language):
    return {
        "id": record["id"],
        "status": record["status"],
        "resolution": record["resolution"],
        "display_name": record["name"][language],
        "vrat_name_en": record["name"]["en"],
        "vrat_name_hi": record["name"]["hi"],
        "weekday": record["weekday"],
        "classification": record["classification"],
        "paksha_detail": record["paksha"],
        "trayodashi": record["tithi"],
        "sunset": record["sunset"],
        "pradosh_kaal": record["pradosh_kaal"],
        "puja_muhurat": record["puja_muhurat"],
        "overlap_minutes": record["overlap_minutes"],
        "lunar_month": record["lunar_month"],
        "candidates": record["candidates"],
        **({"note": record["note"]} if "note" in record else {}),
    }


def _pradosh_calendar_item(record, language):
    item = {"date": record["date"], "anchor_date": record["anchor_date"]}
    item.update(_pradosh_additive(record, language))
    return item


@routes_events.route("/pradosh", methods=["POST"])
def api_pradosh():
    """Pradosh Vrat. Read-only.

    Body (JSON object; every field optional, null = omitted):
      latitude, longitude   default New Delhi; must be inside the supported region
      date                  YYYY-MM-DD, an IST civil date (default: today in IST)
      language | lang       "en" (default) | "hi" -- selects `display_name`; both languages are always returned
      year                  also return the annual `calendar` for this IST year
    `today`/`next` keep their previous shape (resolved observances only); unresolved
    Trayodashi before `next` are listed separately and never given a date.
    """
    try:
        data = _pradosh_body()
        language = normalise_language(data.get("language") if data.get("language") is not None else data.get("lang"))
        lat, lon = normalise_location(data.get("latitude"), data.get("longitude"))

        date_raw = data.get("date")
        if date_raw is None:
            on_date = pradosh_ist_today()
        else:
            if not isinstance(date_raw, str):
                raise PradoshInputError("'date' must be a YYYY-MM-DD string")
            try:
                on_date = datetime.strptime(date_raw.strip(), "%Y-%m-%d").date()
            except ValueError:
                raise PradoshInputError("'date' must be YYYY-MM-DD")

        year = data.get("year")
        if year is not None:
            if isinstance(year, bool) or not isinstance(year, (int, str)) or not str(year).strip().lstrip("-").isdigit():
                raise PradoshInputError("year must be an integer")
            year = pradosh_validate_year(int(str(year).strip()))

        view = get_pradosh_today_next(on_date=on_date, latitude=lat, longitude=lon)
        body = {
            "today": _pradosh_legacy(view["today"], language),
            "next": _pradosh_legacy(view["next"], language),
            "date": view["date"],
            "timezone": "Asia/Kolkata",
            "language": language,
            "location": {**view["location"],
                         "is_default": (lat, lon) == (PRADOSH_DEFAULT_LATITUDE, PRADOSH_DEFAULT_LONGITUDE)},
            "unresolved_before_next": [_pradosh_calendar_item(r, language) for r in view["unresolved_before_next"]],
        }
        if year is not None:
            body["year"] = year
            body["calendar"] = [_pradosh_calendar_item(r, language)
                                for r in get_pradosh_calendar(year, latitude=lat, longitude=lon)]
        body["meta"] = pradosh_convention()
        return jsonify(body)

    except PradoshInputError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        traceback.print_exc()
        return jsonify({"error": "Pradosh calculation failed"}), 500

@routes_events.route("/sankashti", methods=["POST"])
def api_sankashti():
    try:
        data = request.get_json() or {}

        lat = float(data.get("latitude", 28.61))
        lon = float(data.get("longitude", 77.23))
        date_str = data.get("date")

        if date_str:
            current_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        else:
            current_date = datetime.now().date()

        panchang = calculate_panchang(current_date, lat, lon, "en")

        # ✅ FIX HERE
        today_sankashti = get_sankashti_details(panchang, lat, lon)

        next_sankashti = find_next_sankashti(current_date, lat, lon, "en")

        return jsonify({
            "today": today_sankashti,
            "next": next_sankashti
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@routes_events.route("/amavasya", methods=["POST"])
def api_amavasya():
    try:
        data = request.get_json() or {}

        lat = float(data.get("latitude", 28.61))
        lon = float(data.get("longitude", 77.23))
        date_str = data.get("date")

        if date_str:
            current_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        else:
            current_date = datetime.now().date()

        panchang = calculate_panchang(current_date, lat, lon, "en")

        today_amavasya = get_amavasya_details(panchang)

        next_amavasya = find_next_amavasya(current_date, lat, lon, "en")

        return jsonify({
            "today": today_amavasya,
            "next": next_amavasya
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@routes_events.route("/purnima", methods=["POST"])
def api_purnima():
    try:
        data = request.get_json() or {}

        lat = float(data.get("latitude", 28.61))
        lon = float(data.get("longitude", 77.23))
        date_str = data.get("date")

        if date_str:
            current_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        else:
            current_date = datetime.now().date()

        panchang = calculate_panchang(current_date, lat, lon, "en")

        today_purnima = get_purnima_details(panchang)

        next_purnima = find_next_purnima(current_date, lat, lon, "en")

        return jsonify({
            "today": today_purnima,
            "next": next_purnima
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@routes_events.route("/vinayaka", methods=["POST"])
def api_vinayaka_chaturthi():
    try:
        data = request.get_json() or {}

        lat = float(data.get("latitude", 28.61))
        lon = float(data.get("longitude", 77.23))
        date_str = data.get("date")

        if date_str:
            current_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        else:
            current_date = datetime.now().date()

        panchang = calculate_panchang(current_date, lat, lon, "en")

        today_vinayaka = get_vinayaka_chaturthi_details(panchang)

        next_vinayaka = find_next_vinayaka_chaturthi(
            current_date, lat, lon, "en"
        )

        return jsonify({
            "today": today_vinayaka,
            "next": next_vinayaka
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@routes_events.route("/shivratri", methods=["POST"])
def api_shivratri():
    try:
        data = request.get_json() or {}

        lat = float(data.get("latitude", 28.61))
        lon = float(data.get("longitude", 77.23))
        date_str = data.get("date")

        if date_str:
            current_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        else:
            current_date = datetime.now().date()

        panchang = calculate_panchang(current_date, lat, lon, "en")

        today_shivratri = get_shivratri_details(panchang, lat, lon, "en")
        next_shivratri = find_next_shivratri(current_date, lat, lon, "en")

        return jsonify({"today": today_shivratri, "next": next_shivratri})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@routes_events.route("/sankranti", methods=["POST"])
def api_sankranti():
    try:
        data = request.get_json() or {}

        lat = float(data.get("latitude", 28.61))
        lon = float(data.get("longitude", 77.23))
        date_str = data.get("date")

        if date_str:
            current_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        else:
            current_date = datetime.now().date()

        today_sankranti = get_sankranti_details(
            current_date, lat, lon, "en"
        )

        next_sankranti = find_next_sankranti(
            current_date, lat, lon, "en"
        )

        return jsonify({
            "today": today_sankranti,
            "next": next_sankranti
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    
@routes_events.route("/adhik-maas", methods=["POST"])
def api_adhik_maas():
    try:
        data = request.get_json() or {}

        lat = float(data.get("latitude", 28.61))
        lon = float(data.get("longitude", 77.23))

        year = data.get("year")
        year = int(year) if year else datetime.now().year

        items = detect_adhik_maas(year, lat, lon)

        if items:
            return jsonify({
                "year": year,
                "has_adhik_maas": True,
                "items": items
            })

        return jsonify({
            "year": year,
            "has_adhik_maas": False,
            "message": f"No Adhik Maas in {year}"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _kharmas_body():
    """The JSON body as a dict. Empty body -> {}. Any non-empty body that is
    not a JSON object (malformed JSON, array, string, ...) -> 400, whatever
    the Content-Type."""
    raw = request.get_data(cache=True)
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise KharmasInputError("request body must be valid JSON")
    if not isinstance(data, dict):
        raise KharmasInputError("request body must be a JSON object")
    return data


def _parse_kharmas_instant(data):
    """Optional reference instant ("as of"): `at` (ISO 8601; no offset = IST)
    or `date` (YYYY-MM-DD = 00:00 IST that day). null = omitted. Default: now."""
    at_raw, date_raw = data.get("at"), data.get("date")
    if at_raw is not None and date_raw is not None:
        raise KharmasInputError("send either 'at' or 'date', not both")
    if at_raw is not None:
        if not isinstance(at_raw, str):
            raise KharmasInputError("'at' must be an ISO 8601 string")
        try:
            return datetime.fromisoformat(at_raw.strip().replace("Z", "+00:00"))
        except ValueError:
            raise KharmasInputError("'at' must be an ISO 8601 date-time, e.g. 2026-12-16T10:25:00+05:30")
    if date_raw is not None:
        if not isinstance(date_raw, str):
            raise KharmasInputError("'date' must be a YYYY-MM-DD string")
        try:
            return datetime.strptime(date_raw.strip(), "%Y-%m-%d").replace(tzinfo=IST)
        except ValueError:
            raise KharmasInputError("'date' must be YYYY-MM-DD")
    return datetime.now(IST)   # resolved ONCE so status and periods share one "as of"


def _parse_kharmas_year(data):
    year = data.get("year")
    if year is None:
        return None
    if isinstance(year, bool) or not isinstance(year, (int, str)):
        raise KharmasInputError("year must be an integer")
    text = str(year).strip()
    if not text.lstrip("-").isdigit() or len(text) > 6:
        raise KharmasInputError("year must be an integer")
    return int(text)


@routes_events.route("/kharmas", methods=["POST"])
def api_kharmas():
    """Kharmas (Sun in Dhanu / Meena). Read-only.

    Body (JSON object; every field optional, null = omitted):
      language | lang  "en" (default) | "hi"
      latitude, longitude   numbers; used only for Sankranti observance dates
      at | date        the "as of" instant for all statuses (default now)
      year             also list the two periods that START in this year
    `year` and `at` are independent: `year` selects which periods are listed,
    `at` decides their status and previous/current/upcoming.
    """
    try:
        data = _kharmas_body()
        language = data.get("language")
        if language is None:
            language = data.get("lang")
        lat, lon = data.get("latitude"), data.get("longitude")
        at = _parse_kharmas_instant(data)
        year = _parse_kharmas_year(data)

        status = get_kharmas_status(at=at, language=language, latitude=lat, longitude=lon)
        language = (language or "en").strip().lower()
        ephemeris = set(status["ephemeris"])

        body = {
            "as_of": status["as_of"],
            "timezone": "Asia/Kolkata",
            "language": language,
            "is_kharmas": status["is_kharmas"],
            "previous": status["previous"],
            "current": status["current"],
            "upcoming": status["upcoming"],
        }
        if year is not None:
            body["year"] = year
            body["periods"] = get_kharmas_periods(year, language=language, latitude=lat, longitude=lon, at=at)
            ephemeris.update(ephemeris_for_year(year))

        body["meta"] = {
            "definition": "Sun (sidereal) in Dhanu or Meena",
            "interval": "start inclusive, end exclusive (ingress instants)",
            "semantics": {
                "as_of": "reference instant for every status and for previous/current/upcoming",
                "year": "selects the periods listed in `periods`: the two that start in that IST calendar year",
            },
            "observance_rule": "Sankranti observance date: ingress before local sunset -> same day, otherwise next day",
            "observance_supported": observance_supported(_round_coord_for_meta(lat, DEFAULT_LATITUDE),
                                                         _round_coord_for_meta(lon, DEFAULT_LONGITUDE)),
            "observance_supported_region": {"latitude": list(OBSERVANCE_LAT_RANGE), "longitude": list(OBSERVANCE_LON_RANGE),
                                            "note": "outside this region observance_date is null (IST-based sunrise model)"},
            "ayanamsa": "Lahiri (Swiss Ephemeris SIDM_LAHIRI)",
            "ephemeris": sorted(ephemeris),
            "search_resolution_seconds": SEARCH_RESOLUTION_SECONDS,
            "accuracy_note": "Search resolution is 1 s. Ephemeris differences are ~2 s. Published Panchangs "
                             "may differ by several minutes (Drik Panchang: 2-7 min later, 2025-2028; cause not established).",
            "supported_years": [MIN_YEAR, MAX_YEAR],
            "supported_as_of_years": [AS_OF_MIN_YEAR, AS_OF_MAX_YEAR],
        }
        return jsonify(body)

    except KharmasInputError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        traceback.print_exc()
        return jsonify({"error": "Kharmas calculation failed"}), 500

import os
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EKADASHI_DIR = os.path.join(BASE_DIR, "data", "ekadashi")


def find_next_ekadashi_from_json(today):
    year = today.year

    for y in [year, year + 1]:
        file_path = os.path.join(EKADASHI_DIR, f"ekadashi_{y}.json")

        if not os.path.exists(file_path):
            continue

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        ekadashi_list = data.get("ekadashi_list", [])

        future = [
            e for e in ekadashi_list
            if datetime.strptime(e["vrat_date"], "%Y-%m-%d").date() >= today
        ]

        if future:
            future.sort(
                key=lambda x: datetime.strptime(x["vrat_date"], "%Y-%m-%d")
            )

            next_item = future[0]

            return {
                "name": next_item.get("name_en"),  # ✅ correct key
                "date": next_item["vrat_date"],
                "slug": f"/ekadashi/{next_item['slug']}"
            }

    return None


@routes_events.route("/home-upcoming", methods=["POST"])
def api_home_upcoming():
    try:
        data = request.get_json() or {}

        lat = float(data.get("latitude", 28.61))
        lon = float(data.get("longitude", 77.23))
        today = datetime.now().date()

        events = []

        # 🔹 Helper: normalize engine response safely
        def extract_next(engine_response):
            if not engine_response:
                return None

            # 🔹 Case 1: wrapped {"today":..., "next": {...}}
            if isinstance(engine_response, dict) and "next" in engine_response:
                next_data = engine_response.get("next")
            else:
                # 🔹 Case 2: direct event object
                next_data = engine_response

            if not next_data:
                return None

            name = next_data.get("name_en") or next_data.get("name")
            date_value = next_data.get("date")
            slug_value = next_data.get("slug")

            if not name or not date_value or not slug_value:
                return None

            return {
                "name": name,
                "date": date_value,
                "slug": f"/{slug_value}"
            }

        # 🔹 Engine-based events
        events.append(extract_next(find_next_pradosh(today, lat, lon, "en")))
        events.append(extract_next(find_next_sankashti(today, lat, lon, "en")))
        events.append(extract_next(find_next_amavasya(today, lat, lon, "en")))
        events.append(extract_next(find_next_purnima(today, lat, lon, "en")))
        events.append(extract_next(find_next_shivratri(today, lat, lon, "en")))
        events.append(extract_next(find_next_sankranti(today, lat, lon, "en")))

        # 🔹 Ekadashi (JSON-based)
        ekadashi_event = find_next_ekadashi_from_json(today)
        if ekadashi_event:
            events.append(ekadashi_event)

        # 🔹 Remove invalid
        events = [e for e in events if e and e.get("date")]

        # 🔹 Safe date sorting
        events.sort(
            key=lambda x: datetime.strptime(x["date"], "%Y-%m-%d")
        )

        return jsonify({
            "events": events[:5]
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500