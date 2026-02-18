from flask import Blueprint, request, jsonify
from datetime import datetime
from services.festivals.holi_engine import detect_holi

routes_festivals = Blueprint("routes_festivals", __name__)

@routes_festivals.route("/holi", methods=["POST"])
def api_holi():
    try:
        data = request.get_json() or {}

        lat = float(data.get("latitude", 28.61))
        lon = float(data.get("longitude", 77.23))

        year = data.get("year")
        if year:
            year = int(year)
        else:
            year = datetime.now().year

        result = detect_holi(year, lat, lon, "en")

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500
