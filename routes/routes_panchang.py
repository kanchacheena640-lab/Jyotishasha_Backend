# routes/routes_panchang.py

import traceback
from flask import Blueprint, request, jsonify
from services.panchang_engine import calculate_panchang, today_and_tomorrow
from services.muhurth_engine import (
    next_best_dates,
    next_best_dates_for_month
)
from datetime import datetime, timedelta
from services.sun_calc import calculate_sunrise_sunset
from services.moon_calc import get_moon_rise_set
from datetime import date
from services.kharmas_awareness import annotate_muhurat_results, awareness_level

routes_panchang = Blueprint("routes_panchang", __name__)


def _with_kharmas_awareness(response, activity, lat, lon, language, window_start, window_end):
    """Kharmas AWARENESS (never a restriction): for marriage / grah_pravesh /
    naamkaran, return a NEW response dict whose results carry additive
    "kharmas" metadata plus a top-level "kharmas_awareness" block. Every other
    activity, and ANY failure, returns `response` itself untouched -- the
    annotator works on a deep copy and the swap happens only after it succeeded."""
    if awareness_level(activity) is None:
        return response
    try:
        annotated = annotate_muhurat_results(activity, response["results"], lat, lon, language,
                                             window_start, window_end)
        if annotated is None:
            return response
        results, awareness = annotated
        return {**response, "results": results, "kharmas_awareness": awareness}
    except Exception:
        print(">> Kharmas awareness failed; returning the unannotated Muhurat response")
        traceback.print_exc()
        return response

# ------------------- HELPER ------------------- #
def validate_lat_lon(data):
    lat = data.get("latitude")
    lon = data.get("longitude")

    if lat is None or lon is None:
        return None, None, "latitude and longitude required"

    try:
        return float(lat), float(lon), None
    except:
        return None, None, "Invalid latitude/longitude format"

# ------------------- PANCHANG (Today, Tomorrow, or Custom) ------------------- #
@routes_panchang.route("/api/panchang", methods=["POST"])
def api_panchang():
    try:
        data = request.get_json() or {}
        print(">> Panchang Payload Received:", data)

        lat = float(data.get("latitude", 28.61))
        lon = float(data.get("longitude", 77.23))
        date_str = data.get("date")

        # ⭐ LANGUAGE PICK (MAIN FIX)
        language = (data.get("language") or data.get("lang") or "en").lower()
        if language not in ["en", "hi"]:
            language = "en"

        if not date_str:
            print(">> Returning today & tomorrow")
            return jsonify(today_and_tomorrow(lat, lon, language))

        try:
            custom_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            return jsonify({"error": "Invalid date format. Use YYYY-MM-DD."}), 400

        next_day = custom_date + timedelta(days=1)

        print(">> Selected Date:", custom_date, "| Next:", next_day)

        result = {
            "selected_date": calculate_panchang(custom_date, lat, lon, language),
            "next_date": calculate_panchang(next_day, lat, lon, language)
        }

        return jsonify(result)

    except Exception as e:
        print(">> Panchang Error:")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# ------------------- MUHURTH TOOL (30-day scan) ------------------- #
@routes_panchang.route("/api/muhurth/list", methods=["POST"])
def api_muhurth_list():
    """
    Muhurth Finder API
    - Required: activity, latitude, longitude
    - Optional: days (default 30), top_k (default 10)
    - Optional: language ("hi" for Hindi, default English)
    """
    try:
        data = request.get_json() or {}
        print(">> Muhurth Payload Received:", data)

        activity = data.get("activity")
        lat = float(data.get("latitude"))
        lon = float(data.get("longitude"))
        days = int(data.get("days", 30))
        top_k = int(data.get("top_k", 10))

        if not activity:
            return jsonify({"error": "Missing 'activity' field"}), 400

        # ⭐ SAFE LANGUAGE HANDLING (Same rule as Panchang)
        language = (data.get("language") or data.get("lang") or "en").lower()
        if language != "hi":     # any value other than "hi" → English
            language = "en"

        print(">> Muhurth Language:", language)

        # ⭐ Pass language to next_best_dates()
        skipped_dates = []
        results = next_best_dates(
            activity,
            lat,
            lon,
            days=days,
            top_k=top_k,
            language=language,
            skipped=skipped_dates
        )

        response = {
            "activity": activity,
            "window_days": days,
            "language": language,
            "results": results,
            # Days that could not be calculated (logged server-side); normally empty.
            "skipped_dates": skipped_dates
        }
        # Same "today" expression as next_best_dates() uses for its window.
        window_start = datetime.now().date()
        response = _with_kharmas_awareness(response, activity, lat, lon, language,
                                           window_start, window_start + timedelta(days=days))
        return jsonify(response)

    except Exception as e:
        print(">> Muhurth Error:", e)
        return jsonify({"error": str(e)}), 500
    

# ------------------- MUHURTH MONTH API ------------------- #
@routes_panchang.route("/api/muhurth/month", methods=["POST"])
def api_muhurth_month():
    """
    Month-based Muhurth API

    Required:
    - activity
    - month
    - year
    - latitude
    - longitude

    Optional:
    - top_k (default 50)
    - language ("hi" or "en")
    """

    try:
        data = request.get_json() or {}

        print(">> Muhurth Month Payload Received:", data)

        activity = data.get("activity")

        if not activity:
            return jsonify({
                "error": "Missing 'activity' field"
            }), 400

        month = int(data.get("month"))
        year = int(data.get("year"))

        lat = float(data.get("latitude"))
        lon = float(data.get("longitude"))

        top_k = int(data.get("top_k", 50))

        language = (
            data.get("language")
            or data.get("lang")
            or "en"
        ).lower()

        if language != "hi":
            language = "en"

        skipped_dates = []
        results = next_best_dates_for_month(
            activity=activity,
            lat=lat,
            lon=lon,
            month=month,
            year=year,
            top_k=top_k,
            language=language,
            skipped=skipped_dates
        )

        response = {
            "activity": activity,
            "month": month,
            "year": year,
            "language": language,
            "results": results,
            # Days that could not be calculated (logged server-side); normally empty.
            "skipped_dates": skipped_dates
        }
        month_start = date(year, month, 1)
        month_end = date(year + (month == 12), month % 12 + 1, 1)
        response = _with_kharmas_awareness(response, activity, lat, lon, language,
                                           month_start, month_end)
        return jsonify(response)

    except Exception as e:
        print(">> Muhurth Month Error:")
        traceback.print_exc()

        return jsonify({
            "error": str(e)
        }), 500



# ------------------- SUNRISE / SUNSET ------------------- #
@routes_panchang.route("/api/panchang/sun", methods=["POST"])
def api_sunrise_sunset():
    """
    Returns sunrise and sunset for given date & coordinates.

    Expected JSON body:
    {
        "latitude": 28.6139,
        "longitude": 77.2090,
        "date": "2025-10-05"
    }
    """

    try:
        data = request.get_json(silent=True) or {}

        # ✅ Latitude / Longitude Validation
        lat, lon, error = validate_lat_lon(data)
        if error:
            return jsonify({
                "success": False,
                "error": error
            }), 400

        # ✅ Date Validation
        date_str = data.get("date")
        if date_str:
            try:
                target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                return jsonify({
                    "success": False,
                    "error": "Invalid date format. Use YYYY-MM-DD."
                }), 400
        else:
            target_date = date.today()

        # ✅ Calculation
        sunrise, sunset = calculate_sunrise_sunset(target_date, lat, lon)

        if not sunrise or not sunset:
            return jsonify({
                "success": False,
                "error": "Sunrise/sunset calculation failed."
            }), 500

        # ✅ Success Response
        return jsonify({
            "success": True,
            "data": {
                "date": target_date.strftime("%Y-%m-%d"),
                "latitude": lat,
                "longitude": lon,
                "sunrise": sunrise.strftime("%H:%M:%S"),
                "sunset": sunset.strftime("%H:%M:%S")
            }
        }), 200

    except Exception:
        return jsonify({
            "success": False,
            "error": "Internal server error"
        }), 500
    
# ------------------- MOONRISE / MOONSET ------------------- #
@routes_panchang.route("/api/panchang/moon", methods=["POST"])
def api_moon_rise_set():
    """
    Returns moonrise and moonset for given date & coordinates.

    Expected JSON body:
    {
        "latitude": 28.6139,
        "longitude": 77.2090,
        "date": "2025-10-05"
    }
    """

    try:
        data = request.get_json(silent=True) or {}

        # ✅ Latitude / Longitude Validation
        lat, lon, error = validate_lat_lon(data)
        if error:
            return jsonify({
                "success": False,
                "error": error
            }), 400

        # ✅ Date Validation
        date_str = data.get("date")
        if date_str:
            try:
                target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                return jsonify({
                    "success": False,
                    "error": "Invalid date format. Use YYYY-MM-DD."
                }), 400
        else:
            target_date = date.today()

        # ✅ Calculation
        moon_data = get_moon_rise_set(target_date, lat, lon)

        if moon_data is None:
            return jsonify({
                "success": False,
                "error": "Moon calculation failed."
            }), 500

        # ✅ Success Response
        return jsonify({
            "success": True,
            "data": {
                "date": target_date.strftime("%Y-%m-%d"),
                "latitude": lat,
                "longitude": lon,
                "moonrise": moon_data.get("moonrise"),
                "moonset": moon_data.get("moonset")
            }
        }), 200

    except Exception:
        return jsonify({
            "success": False,
            "error": "Internal server error"
        }), 500