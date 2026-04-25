from flask import Blueprint, request, jsonify
from services.panchang_engine import calculate_panchang
from services.card_service import generate_cards

cards_bp = Blueprint("cards", __name__, url_prefix="/api/cards")


@cards_bp.route("", methods=["POST"])
def get_cards():
    data = request.get_json()

    date = data.get("date")
    lat = data.get("lat")
    lng = data.get("lng")

    if not date or not lat or not lng:
        return jsonify({"error": "Missing required fields"}), 400

    # 🔹 Panchang calculate
    panchang_data = calculate_panchang(
        date=date,
        latitude=lat,
        longitude=lng
    )

    # 🔹 Events (abhi empty, baad me connect karenge)
    events = []

    # 🔹 Cards generate
    cards = generate_cards(panchang_data, events)

    return jsonify({
        "cards": cards
    })