# routes/routes_chat_requirement.py

from flask import Blueprint, request, jsonify
from modules.services.chat_requirement_engine import get_required_data
import json
import re

routes_chat_requirement = Blueprint("routes_chat_requirement", __name__)


def extract_json(text: str):
    """
    Extract JSON even if GPT returns:
    - pure JSON
    - JSON wrapped in a string
    - escaped JSON
    - extra text before/after
    """
    if not text:
        return None

    # 1️⃣ Try direct JSON
    try:
        return json.loads(text)
    except:
        pass

    # 2️⃣ Extract JSON block {...}
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None

    block = match.group(0)

    # 3️⃣ Try load again
    try:
        return json.loads(block)
    except:
        pass

    # 4️⃣ Fix escaped JSON → unescape
    try:
        unescaped = block.encode().decode("unicode_escape")
        return json.loads(unescaped)
    except:
        pass

    # 5️⃣ Last fix → Some models wrap JSON inside a string literal
    # Example: "\"{ \\\"required_data\\\": [ ... ] }\""
    try:
        # remove surrounding quotes
        if block.startswith('"') and block.endswith('"'):
            block2 = block[1:-1]
            unescaped2 = block2.encode().decode("unicode_escape")
            return json.loads(unescaped2)
    except:
        pass

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
