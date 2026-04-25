from flask import Blueprint, request, jsonify
from services.panchang_engine import today_and_tomorrow
from services.card_service import generate_cards

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

        panchang_data = today_and_tomorrow(lat, lng)

        cards = generate_cards(panchang_data, events=[])

        return jsonify({
            "cards": cards
        })

    except Exception as e:
        print("CARDS API ERROR:", str(e))
        return jsonify({"error": "Internal server error"}), 500