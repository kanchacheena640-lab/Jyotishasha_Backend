# routes/routes_free_consult.py
from flask import Blueprint, request, jsonify

routes_free_consult = Blueprint("routes_free_consult", __name__)

@routes_free_consult.route("/api/free-consult", methods=["POST"])
def free_consult():
    data = request.get_json() or {}

    # Basic input checks (astrology-only; numerology not used)
    if "question" not in data or "birth" not in data:
        return jsonify({"error": "Missing fields: 'question' and 'birth'"}), 400

    birth = data["birth"] or {}
    required_birth = ["name", "dob", "tob", "pob", "lat", "lng", "tz"]
    missing = [k for k in required_birth if k not in birth]
    if missing:
        return jsonify({"error": f"Missing birth fields: {', '.join(missing)}"}), 400

    # Stub success (next step me kundali + transit + dasha logic add karenge)
    return jsonify({
        "status": "ok",
        "message": "Ask Now API wired. Proceed to Step 2 for astro logic."
    }), 200
