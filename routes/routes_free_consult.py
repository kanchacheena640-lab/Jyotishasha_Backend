from flask import Blueprint, request, jsonify
from services.full_kundali_service import calculate_full_kundali
from transit_engine import get_current_positions  # ✅ correct import

routes_free_consult = Blueprint("routes_free_consult", __name__)

@routes_free_consult.route("/api/free-consult", methods=["POST"])
def free_consult():
    data = request.get_json() or {}
    birth = data.get("birth", {})
    question = data.get("question", "").strip()

    # 1️⃣ Basic validation
    required = ["name", "dob", "tob", "pob", "lat", "lng", "tz"]
    missing = [k for k in required if not birth.get(k)]
    if missing or not question:
        return jsonify({"error": f"Missing fields: {', '.join(missing)} or question"}), 400

    # 2️⃣ Kundali calculation
    kundali_data = calculate_full_kundali(
        birth["name"], birth["dob"], birth["tob"], birth["pob"],
        float(birth["lat"]), float(birth["lng"]), float(birth["tz"])
    )

    # 3️⃣ Transit snapshot (current planetary positions)
    try:
        transit_data = get_current_positions()
    except Exception as e:
        transit_data = {"error": str(e)}

    # 4️⃣ Dasha summary (from kundali_data)
    dasha_summary = kundali_data.get("dasha_summary", "No dasha info")

    # 5️⃣ Prompt preparation (GPT call in next step)
    prompt = f"""
    User Question: {question}
    Birth Chart Summary: {kundali_data.get('summary', '')}
    Dasha Summary: {dasha_summary}
    Transit Summary: {transit_data}
    Rules:
    - Give astrological possibilities only.
    - No health or legal advice.
    - Add disclaimer: 'This answer is for astrological guidance only.'
    """

    return jsonify({
        "status": "ok",
        "kundali_preview": kundali_data.get("ascendant", {}),
        "dasha_preview": dasha_summary,
        "transit_preview": transit_data,
        "prompt_preview": prompt[:500] + "..."
    }), 200
