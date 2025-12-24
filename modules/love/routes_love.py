from __future__ import annotations

from flask import Blueprint, request, jsonify

from modules.love.service_love import run_love_compatibility, LoveServiceError


love_bp = Blueprint("love", __name__, url_prefix="/api/love")


def _is_blank(v) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


@love_bp.route("/compatibility", methods=["POST"])
def love_compatibility():
    payload = request.get_json(silent=True) or {}
    user = payload.get("user") or {}
    partner = payload.get("partner") or {}

    if _is_blank(partner.get("name")) or _is_blank(partner.get("dob")):
        return jsonify({
            "ok": False,
            "error": "PARTNER_DOB_REQUIRED",
            "message": "Partner name and date of birth are required for Vedic love analysis."
        }), 400

    try:
        result = run_love_compatibility(
            user=user,
            partner=partner,
            boy_is_user=payload.get("boy_is_user", True),
        )

        return jsonify({
            "ok": True,
            "data": result,
        }), 200

    except LoveServiceError as e:
        return jsonify({
            "ok": False,
            "error": "LOVE_SERVICE_ERROR",
            "message": str(e),
        }), 400

    except Exception:
        return jsonify({
            "ok": False,
            "error": "INTERNAL_ERROR",
            "message": "Internal server error",
        }), 500
