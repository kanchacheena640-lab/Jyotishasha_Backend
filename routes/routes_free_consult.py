from flask import Blueprint, request, jsonify
from services.full_kundali_service import generate_full_kundali_payload   # ✅ use aggregator
from transit_engine import get_current_positions

routes_free_consult = Blueprint("routes_free_consult", __name__)

@routes_free_consult.route("/api/free-consult", methods=["POST"])
def free_consult():
    data = request.get_json() or {}
    birth = data.get("birth", {})
    question = data.get("question", "").strip()

    # 1) Validate
    required = ["name", "dob", "tob", "pob", "lat", "lng", "tz"]
    missing = [k for k in required if not birth.get(k)]
    if missing or not question:
        return jsonify({"error": f"Missing fields: {', '.join(missing)} or question"}), 400

    # 2) Kundali (aggregator—NO direct calculate_full_kundali call here)
    try:
        kundali_data = generate_full_kundali_payload({
            "name": birth["name"],
            "dob": birth["dob"],
            "tob": birth["tob"],
            "place_name": birth["pob"],          # ok to send; aggregator ignores if not needed
            "lat": float(birth["lat"]),
            "lng": float(birth["lng"]),
            "timezone": str(birth.get("tz", "+05:30")),
            "language": "en"
        })
    except Exception as e:
        return jsonify({"error": f"Kundali generation failed: {e}"}), 500

    # 3) Current transit snapshot
    try:
        transit_data = get_current_positions()
    except Exception as e:
        transit_data = {"error": str(e)}

    # 4) Dasha summary (safe)
    dasha_summary = kundali_data.get("dasha_summary", {})

    # 5) Prompt (GPT step next)
    prompt = f"""
    User Question: {question}

    Birth Chart Summary: {kundali_data.get('lagna_sign', '')} ascendant.
    Dasha Summary: {dasha_summary}
    Transit Summary: {transit_data}

    Rules:
    - Provide astrological possibilities only.
    - No health or legal advice.
    - Add disclaimer: 'This answer is for astrological guidance only.'
    """

    return jsonify({
        "status": "ok",
        "kundali_preview": kundali_data.get("chart_data", {}).get("ascendant"),
        "dasha_preview": dasha_summary,
        "transit_preview": transit_data,
        "prompt_preview": (prompt[:500] + "...")
    }), 200
