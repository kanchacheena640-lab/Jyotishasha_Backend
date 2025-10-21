from flask import Blueprint, request, jsonify
from services.full_kundali_service import generate_full_kundali_payload

# ✅ Unique blueprint
full_kundali_modern_bp = Blueprint("full_kundali_modern_bp", __name__)

@full_kundali_modern_bp.route("/api/full-kundali-modern", methods=["POST"])
def full_kundali_modern():
    """
    Modern Kundali Report API (Jyotishasha Version)
    Combines base kundali, transits, dasha, remedies, and houses.
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Empty request body"}), 400

        payload = generate_full_kundali_payload(data)
        return jsonify(payload), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
