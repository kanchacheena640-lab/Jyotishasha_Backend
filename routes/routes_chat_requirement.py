from flask import Blueprint, request, jsonify
from modules.services.chat_requirement_engine import get_required_data
import json
import re

routes_chat_requirement = Blueprint("routes_chat_requirement", __name__)


def clean_json_text(text):
    """
    Removes everything before/after JSON block.
    Ensures only the JSON object is extracted.
    """
    try:
        # Extract JSON {...}
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            return match.group(0)
        return text
    except:
        return text


@routes_chat_requirement.route("/api/chat/requirements", methods=["POST"])
def get_requirements():
    data = request.get_json() or {}
    question = data.get("question", "").strip()

    if not question:
        return jsonify({"success": False, "error": "Missing 'question'"}), 400

    try:
        raw = get_required_data(question)

        cleaned = clean_json_text(raw)

        try:
            req_json = json.loads(cleaned)
        except Exception:
            return jsonify({
                "success": False,
                "error": "GPT returned invalid JSON",
                "raw": raw,
                "cleaned": cleaned
            }), 500

        return jsonify({
            "success": True,
            "requirements": req_json
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
