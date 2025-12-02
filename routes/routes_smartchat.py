    # routes/routes_smartchat.py

from flask import Blueprint, request, jsonify
from modules.smartchat.smartchat_engine import run_smartchat

routes_smartchat = Blueprint("routes_smartchat", __name__)

@routes_smartchat.route("/api/smartchat", methods=["POST"])
def smartchat_api():
    data = request.get_json() or {}

    question = data.get("question", "").strip()
    birth = data.get("birth", {})

    if not question:
        return jsonify({"success": False, "error": "Missing question"}), 400

    if not birth:
        return jsonify({"success": False, "error": "Missing birth details"}), 400

    try:
        result = run_smartchat(birth, question)

        return jsonify({
            "success": True,
            "answer": result["answer"],
            "detected_house": result["detected_house"],
            "chart_preview": result["chart_preview"],
            "kundali_preview": result["kundali_preview"],
            "transit_preview": result["transit_preview"],
            "dasha_preview": result["dasha_preview"],
            "debug_prompt": result["debug_prompt"]  # remove in production if needed
        }), 200

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
