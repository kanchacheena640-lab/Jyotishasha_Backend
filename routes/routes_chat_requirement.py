# routes/routes_chat_requirement.py

from flask import Blueprint, request, jsonify
from modules.services.chat_requirement_engine import get_required_data
import json
import re

routes_chat_requirement = Blueprint("routes_chat_requirement", __name__)


def extract_json(text: str):
    """
    Extracts the { ... } JSON block from GPT output.
    Works even if GPT adds text before/after or escape characters.
    """
    if not text:
        return None

    # Try direct JSON first
    try:
        return json.loads(text)
    except:
        pass

    # Extract JSON block using regex
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None

    block = match.group(0)

    # Try load again
    try:
        return json.loads(block)
    except:
        pass

    # Try unescaping escaped JSON
    try:
        unescaped = block.encode().decode("unicode_escape")
        return json.loads(unescaped)
    except:
        return None


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
        raw = get_required_data(question)  # GPT raw output

        parsed = extract_json(raw)

        if not parsed:
            return jsonify({
                "success": False,
                "error": "Invalid JSON returned from GPT",
                "raw": raw
            }), 500

        return jsonify({
            "success": True,
            "requirements": parsed
        }), 200

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
