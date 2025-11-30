from flask import Blueprint, request, jsonify
from modules.services.chat_requirement_engine import get_required_data
import json

routes_chat_requirement = Blueprint("routes_chat_requirement", __name__)


@routes_chat_requirement.route("/api/chat/requirements", methods=["POST"])
def get_requirements():
    data = request.get_json() or {}
    question = data.get("question", "").strip()

    if not question:
        return jsonify({"success": False, "error": "Missing 'question' field"}), 400

    try:
        raw_json = get_required_data(question)

        # GPT returns JSON string → convert to dict
        try:
            requirements = json.loads(raw_json)
        except Exception:
            return jsonify({
                "success": False,
                "error": "Invalid JSON returned from GPT",
                "raw": raw_json
            }), 500

        return jsonify({
            "success": True,
            "requirements": requirements
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
