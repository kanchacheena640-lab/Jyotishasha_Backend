# routes/routes_chat_requirement.py

from flask import Blueprint, request, jsonify
from modules.services.chat_requirement_engine import get_required_data

print("🔥 routes_chat_requirement loaded")  # DEBUG

routes_chat_requirement = Blueprint("routes_chat_requirement", __name__)


@routes_chat_requirement.route("/api/chat/requirements", methods=["POST"])
def get_requirements():
    data = request.get_json() or {}
    question = data.get("question", "").strip()

    if not question:
        return jsonify({
            "success": False,
            "error": "Missing 'question'"
        }), 400

    try:
        parsed = get_required_data(question)

        print("\n===== FINAL PARSED IN ROUTE =====")
        print(parsed)
        print("=================================\n")

        return jsonify({
            "success": True,
            "requirements": parsed
        }), 200

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
