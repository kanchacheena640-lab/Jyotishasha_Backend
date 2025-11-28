# routes/routes_panchang.py

from flask import Blueprint, request, jsonify
from services.panchang_engine import calculate_panchang, today_and_tomorrow
from services.muhurth_engine import next_best_dates
from datetime import datetime, timedelta
from services.sun_calc import calculate_sunrise_sunset
from datetime import date

routes_panchang = Blueprint("routes_panchang", __name__)

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
        print(">> Panchang Error:", e)
        return jsonify({"error": str(e)}), 500

# ------------------- MUHURTH TOOL (30-day scan) ------------------- #
@routes_panchang.route("/api/muhurth/list", methods=["POST"])
def api_muhurth_list():
    """
    Muhurth Finder API
    - Required: activity, latitude, longitude
    - Optional: days (default 30), top_k (default 10)
    """
    try:
        data = request.get_json() or {}

        activity = data.get("activity")
        lat = float(data.get("latitude"))
        lon = float(data.get("longitude"))
        days = int(data.get("days", 30))
        top_k = int(data.get("top_k", 10))

        if not activity:
            return jsonify({"error": "Missing 'activity' field"}), 400

        results = next_best_dates(activity, lat, lon, days=days, top_k=top_k)

        return jsonify({
            "activity": activity,
            "window_days": days,
            "results": results
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ------------------- SUNRISE / SUNSET ------------------- #
@routes_panchang.route("/api/panchang/sun", methods=["POST"])
def api_sunrise_sunset():
    """
    Returns sunrise and sunset for given date & coordinates.
    Example body:
    {
        "latitude": 28.6139,
        "longitude": 77.2090,
        "date": "2025-10-05"
    }
    """
    try:
        data = request.get_json() or {}
        lat = float(data.get("latitude", 28.6139))
        lon = float(data.get("longitude", 77.2090))
        date_str = data.get("date")

        if date_str:
            y, m, d = map(int, date_str.split("-"))
            target_date = date(y, m, d)
        else:
            target_date = date.today()
            
        print(">> Calling for:", target_date, lat, lon)
        sunrise, sunset = calculate_sunrise_sunset(target_date, lat, lon)
        print(">> Result:", sunrise, sunset)

        if not sunrise or not sunset:
            return jsonify({"error": "Sunrise/sunset calculation failed."}), 500

        return jsonify({
            "date": target_date.strftime("%Y-%m-%d"),
            "latitude": lat,
            "longitude": lon,
            "sunrise": sunrise.strftime("%Y-%m-%d %H:%M:%S"),
            "sunset": sunset.strftime("%Y-%m-%d %H:%M:%S")
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500