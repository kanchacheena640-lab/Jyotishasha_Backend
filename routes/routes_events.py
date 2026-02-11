from flask import Blueprint, request, jsonify
from datetime import datetime
from services.events_engine import get_ekadashi_details, find_next_ekadashi
from services.panchang_engine import calculate_panchang

routes_events = Blueprint("routes_events", __name__)

@routes_events.route("/ekadashi", methods=["POST"])
def api_ekadashi():
    try:
        data = request.get_json() or {}

        lat = float(data.get("latitude", 28.61))
        lon = float(data.get("longitude", 77.23))
        date_str = data.get("date")

        if date_str:
            current_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        else:
            current_date = datetime.now().date()

        # Today's Panchang
        panchang = calculate_panchang(current_date, lat, lon, "en")

        today_ekadashi = get_ekadashi_details(panchang)

        next_ekadashi = find_next_ekadashi(current_date, lat, lon, "en")

        return jsonify({
            "today": today_ekadashi,
            "next": next_ekadashi
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
