from flask import Blueprint, request, jsonify
from services.panchang_engine import calculate_panchang
from services.card_service import generate_cards
from datetime import datetime

cards_bp = Blueprint("cards", __name__, url_prefix="/api/cards")


@cards_bp.route("", methods=["POST"])
def get_cards():
    data = request.get_json(force=True) or {}

    date = data.get("date")
    lat = float(data.get("lat"))
    lng = float(data.get("lng"))

    if not date:
        return jsonify({"error": "date required"}), 400

    # 🔹 Convert to datetime
    date_obj = datetime.strptime(date, "%Y-%m-%d")

    # 🔹 Panchang
    panchang_data = calculate_panchang(date_obj, lat, lng)

    # 🔹 Cards
    cards = generate_cards(panchang_data, events=[])

    return jsonify({
        "cards": cards
    })