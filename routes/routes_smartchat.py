    # routes/routes_smartchat.py

from flask import Blueprint, request, jsonify
from modules.reviews import rate_limit
from modules.smartchat.smartchat_engine import run_smartchat

routes_smartchat = Blueprint("routes_smartchat", __name__)

# PR #8 -- kept only for Android builds <= 1.1.0 (removed from the app in
# 1.1.1+46); unauthenticated and OpenAI-backed, so conservatively limited
# per client IP using the existing Redis limiter (per-process in-memory
# fallback if Redis is unavailable). Generous for a real person, a hard cap
# for scripted abuse. Checked BEFORE any OpenAI call.
SMARTCHAT_LIMITS = (("smartchat-hour", 10, 3600), ("smartchat-day", 30, 86400))


def _rate_limited() -> bool:
    key = rate_limit.client_key(request.remote_addr, request.headers.get("X-Forwarded-For"))
    # every window is counted on every call, so the daily cap still applies
    results = [rate_limit.allow(bucket, key, limit, window) for bucket, limit, window in SMARTCHAT_LIMITS]
    return not all(results)

@routes_smartchat.route("/api/smartchat", methods=["POST"])
def smartchat_api():
    if _rate_limited():
        return jsonify({"success": False, "error": "rate_limited"}), 429

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
            #"detected_house": result["detected_house"],
            #"chart_preview": result["chart_preview"],
            #"kundali_preview": result["kundali_preview"],
            #"transit_preview": result["transit_preview"],
            #"dasha_preview": result["dasha_preview"],
            #"debug_prompt": result["debug_prompt"]  # remove in production if needed
        }), 200

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
