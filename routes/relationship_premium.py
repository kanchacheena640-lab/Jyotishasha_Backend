from flask import Blueprint, request, jsonify

from services.love_service import run_love_compatibility, LoveServiceError

relationship_premium_bp = Blueprint(
    "relationship_premium",
    __name__,
    url_prefix="/api/relationship/premium",
)

@relationship_premium_bp.route("/analyze", methods=["POST"])
def analyze_relationship_premium():
    """
    Premium Love & Relationship analysis
    - No AI here
    - No report writing
    - Pure structured JSON
    """
    try:
        payload = request.get_json(force=True) or {}

        user = payload.get("user") or {}
        partner = payload.get("partner") or {}
        boy_is_user = payload.get("boy_is_user", True)

        result = run_love_compatibility(
            user=user,
            partner=partner,
            boy_is_user=bool(boy_is_user),
        )

        return jsonify({
            "status": "success",
            "data": result,
        })

    except LoveServiceError as e:
        return jsonify({
            "status": "error",
            "error": str(e),
        }), 400

    except Exception:
        # deliberately generic (no internal leaks)
        return jsonify({
            "status": "error",
            "error": "Unable to process relationship analysis",
        }), 500
