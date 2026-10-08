from flask import Blueprint, request, jsonify
from datetime import datetime
from services.festivals.holi_engine import detect_holi
from services.festivals.holi_rashi_tips import generate_holi_rashi_tips
from services.festivals.navratri_engine import detect_navratri, build_full_navratri
from services.festivals.chhath_engine import (
    calculate_chhath, current_ist_year, ChhathInputError, ChhathCalculationError
)

routes_festivals = Blueprint("routes_festivals", __name__)

@routes_festivals.route("/holi", methods=["POST"])
def api_holi():
    try:
        data = request.get_json() or {}

        lat = float(data.get("latitude", 28.61))
        lon = float(data.get("longitude", 77.23))

        year = int(data.get("year")) if data.get("year") else datetime.now().year
        user_moon = data.get("user_moon_sign")  # optional (for app)

        # 🔹 Base Holi Info
        holi_info = detect_holi(year, lat, lon, "en")

        # 🔹 Rashi Tips
        rashi_data = generate_holi_rashi_tips(year, lat, lon, "en")

        response = holi_info or {}

        if rashi_data:
            response["moon_sign_on_holi"] = rashi_data["moon_sign_on_holi"]

            if user_moon:
                sign = user_moon.lower()
                if sign in rashi_data["tips"]:
                    response["personal_rashi_tip"] = rashi_data["tips"][sign]
            else:
                response["rashi_tips"] = rashi_data["tips"]

        return jsonify(response)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------------- NAVRATRI ---------------- #

@routes_festivals.route("/navratri", methods=["POST"])
def api_navratri():
    try:
        data = request.get_json() or {}

        lat = float(data.get("latitude", 28.61))
        lon = float(data.get("longitude", 77.23))

        year = int(data.get("year")) if data.get("year") else datetime.now().year
        navratri_type = data.get("type", "chaitra")  # chaitra / sharadiya

        result = build_full_navratri(year, lat, lon, navratri_type)

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------------- CHHATH ---------------- #

@routes_festivals.route("/chhath", methods=["POST"])
def api_chhath():
    try:
        # Request contract: see services/festivals/chhath_engine.py docstring.
        # Missing/non-JSON body -> all defaults; a JSON body must be an object.
        data = request.get_json(silent=True)
        if data is None:
            data = {}
        if not isinstance(data, dict):
            return jsonify({"error": "Request body must be a JSON object", "code": "INVALID_BODY"}), 400

        year = data.get("year")
        if year is None:
            year = current_ist_year()

        result = calculate_chhath(
            year,
            city=data.get("city"),
            latitude=data.get("latitude"),
            longitude=data.get("longitude"),
            language=data.get("language"),
            festival_type=data.get("type"),
        )

        return jsonify(result)

    except ChhathInputError as e:
        return jsonify({"error": str(e), "code": e.code}), 400

    except ChhathCalculationError as e:
        return jsonify({"error": str(e), "code": e.code}), 422

    except Exception:
        return jsonify({"error": "Chhath calculation failed", "code": "ENGINE_ERROR"}), 500
