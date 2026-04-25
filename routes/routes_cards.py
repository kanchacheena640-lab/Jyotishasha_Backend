from flask import Blueprint, request, jsonify
from services.panchang_engine import today_and_tomorrow
from services.card_service import generate_cards
from services.events_engine import get_events_for_date
from datetime import datetime

cards_bp = Blueprint("cards", __name__, url_prefix="/api/cards")


@cards_bp.route("", methods=["POST"])
def get_cards():
    try:
        data = request.get_json(force=True) or {}

        if not data.get("lat") or not data.get("lng"):
            return jsonify({"error": "lat & lng required"}), 400

        try:
            lat = float(data.get("lat"))
            lng = float(data.get("lng"))
        except:
            return jsonify({"error": "invalid lat/lng"}), 400

        # 🔹 Panchang
        panchang_data = today_and_tomorrow(lat, lng, "en")

        # 🔹 Date
        date_str = data.get("date")
        date_obj = (
            datetime.strptime(date_str, "%Y-%m-%d")
            if date_str
            else datetime.now()
        )

        # 🔥 REAL EVENTS
        events = get_events_for_date(date=date_obj, lat=lat, lon=lng)

        # 🔹 Generate cards (FIXED)
        cards = generate_cards(panchang_data, events)

        return jsonify({
            "cards": cards
        })

    except Exception as e:
        print("🔥 CARDS API ERROR:", str(e))
        return jsonify({"error": "Internal server error"}), 500