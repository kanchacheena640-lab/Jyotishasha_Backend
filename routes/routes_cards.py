from flask import Blueprint, request, jsonify
from services.panchang_engine import today_and_tomorrow
from services.card_service import generate_cards
from models import AstroEvent
from datetime import datetime

cards_bp = Blueprint("cards", __name__, url_prefix="/api/cards")


@cards_bp.route("", methods=["POST"])
def get_cards():
    try:
        data = request.get_json(force=True) or {}

        # ✅ Required fields
        if not data.get("lat") or not data.get("lng"):
            return jsonify({"error": "lat & lng required"}), 400

        # ✅ Safe float conversion
        try:
            lat = float(data.get("lat"))
            lng = float(data.get("lng"))
        except:
            return jsonify({"error": "invalid lat/lng"}), 400

        # 🔹 Panchang
        panchang_data = today_and_tomorrow(lat, lng, "en")

        # 🔹 Date handling
        date_str = data.get("date")
        date_obj = (
            datetime.strptime(date_str, "%Y-%m-%d").date()
            if date_str
            else datetime.now().date()
        )

        # 🔥 EVENTS FROM DB
        events_db = AstroEvent.query.filter_by(date=date_obj).all()

        events = [
            {
                "type": e.type,
                "name": e.name,
                "meta": e.meta or {}
            }
            for e in events_db
        ]

        # 🔹 Generate cards
        cards = generate_cards(panchang_data, events)

        return jsonify({
            "cards": cards
        })

    except Exception as e:
        print("🔥 CARDS API ERROR:", str(e))
        return jsonify({"error": "Internal server error"}), 500