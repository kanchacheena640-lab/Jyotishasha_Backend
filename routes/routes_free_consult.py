"""
DEPRECATED FILE — DO NOT USE

This 'routes_free_consult.py' was originally created to handle the old 
Free Consultation flow (full kundali → transit → GPT answer).

This logic is now REPLACED by the new unified chat system:

✓ 1 Free Question Per Day
✓ ₹51 Chat Pack (8 Questions)
✓ Single Unified Endpoint in: routes/routes_chat.py
✓ Shared engine in: services/chat_engine.py
✓ Daily quota tracking in: models_free_daily.py
✓ Paid pack tracking in: models_chat_pack.py

This file is kept ONLY to preserve old code reference and avoid accidental 
errors. Do NOT register or import this route in the current production app.
"""


from flask import Blueprint, request, jsonify
from services.full_kundali_service import generate_full_kundali_payload  # ✅ correct path (no api)
from transit_engine import get_current_positions
from openai import OpenAI
import os

routes_free_consult = Blueprint("routes_free_consult", __name__)

# 🔑 Initialize OpenAI client once
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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

    # 2️⃣ Kundali generation
    try:
        kundali_data = generate_full_kundali_payload({
            "name": birth["name"],
            "dob": birth["dob"],
            "tob": birth["tob"],
            "place_name": birth["pob"],
            "lat": float(birth["lat"]),
            "lng": float(birth["lng"]),
            "timezone": str(birth.get("tz", "+05:30")),
            "language": "en"
        })
    except Exception as e:
        return jsonify({"error": f"Kundali generation failed: {e}"}), 500

    # 3️⃣ Current planetary transit snapshot
    try:
        transit_data = get_current_positions()
    except Exception as e:
        transit_data = {"error": str(e)}

    # 4️⃣ Dasha summary
    dasha_summary = kundali_data.get("dasha_summary", {})

    # 5️⃣ Prepare GPT prompt
    prompt = f"""
    User Question: {question}

    Birth Chart Summary: {kundali_data.get('lagna_sign', '')} ascendant.
    Dasha Summary: {dasha_summary}
    Transit Summary: {transit_data}

    Instructions:
    - You are a senior Vedic astrologer.
    - Give a concise (4–6 line) astrological insight answering the question.
    - Avoid health or legal advice.
    - Add this line at the end: 'This answer is for astrological guidance only.'
    """

    # 6️⃣ Call GPT
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a senior Vedic astrologer."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
        )
        gpt_answer = response.choices[0].message.content.strip()
    except Exception as e:
        gpt_answer = f"(AI temporarily unavailable) Error: {e}"

    # 7️⃣ Final JSON response
    return jsonify({
        "status": "ok",
        "kundali_preview": kundali_data.get("chart_data", {}).get("ascendant"),
        "dasha_preview": dasha_summary,
        "transit_preview": transit_data,
        "answer": gpt_answer,
        "disclaimer": "This answer is for astrological guidance only."
    }), 200
