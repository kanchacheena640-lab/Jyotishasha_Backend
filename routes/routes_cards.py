from flask import Blueprint, request, jsonify
from services.panchang_engine import today_and_tomorrow
from services.card_service import generate_cards

cards_bp = Blueprint("cards", __name__, url_prefix="/api/cards")


@cards_bp.route("", methods=["POST"])
def get_cards():
    try:
        data = request.get_json(force=True) or {}

        # ✅ Required fields check
        if not data.get("lat") or not data.get("lng"):
            return jsonify({"error": "lat & lng required"}), 400

        # ✅ Safe float conversion
        try:
            lat = float(data.get("lat"))
            lng = float(data.get("lng"))
        except:
            return jsonify({"error": "invalid lat/lng"}), 400

        # ✅ Panchang (CORRECT STRUCTURE)
        panchang_data = today_and_tomorrow(lat, lng, "en")

        # 🔥 SAFETY FIX (IMPORTANT — root cause fix)
        if "selected_date" not in panchang_data or "next_date" not in panchang_data:
            print("⚠️ WRONG PANCHANG STRUCTURE:", panchang_data.keys())
            return jsonify({"error": "panchang structure invalid"}), 500

        # ✅ Generate cards
        cards = generate_cards(panchang_data, events=[])

        return jsonify({
            "cards": cards
        })

    except Exception as e:
        print("🔥 CARDS API ERROR:", str(e))
        return jsonify({"error": "Internal server error"}), 500