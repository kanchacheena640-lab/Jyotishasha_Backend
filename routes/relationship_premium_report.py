# routes/relationship_premium_report.py

from flask import Blueprint, request, jsonify

from modules.love.service_love import run_love_compatibility, LoveServiceError
from modules.love.love_report_compiler import compile_love_report

relationship_premium_report_bp = Blueprint(
    "relationship_premium_report",
    __name__,
    url_prefix="/api/relationship/premium",
)


@relationship_premium_report_bp.route("/love-marriage-report", methods=["POST"])
def love_marriage_life_report():
    """
    Paid Love → Marriage Life Premium Report
    - No AI
    - Uses locked compiler
    - Frontend-ready JSON
    """
    try:
        payload = request.get_json(force=True) or {}

        user = payload.get("user") or {}
        partner = payload.get("partner") or {}
        boy_is_user = payload.get("boy_is_user", True)
        language = payload.get("language", "en")

        # Step 1: core compatibility + kundali logic
        analysis = run_love_compatibility(
            user=user,
            partner=partner,
            boy_is_user=bool(boy_is_user),
        )

        # Step 2: build compiler payload (LOCKED STRUCTURE)
        report_payload = {
            "language": language,
            "client": {
                "name": user.get("name"),
                "dob": user.get("dob"),
                "tob": user.get("tob"),
                "pob": user.get("pob"),
            },
            "kundali": analysis.get("kundali") or {},
            "ashtakoot": analysis.get("ashtakoot") or {},
            "dasha": analysis.get("dasha") or {},
            "transits": analysis.get("transits") or {},
        }

        # Step 3: compile final paid report
        report = compile_love_report(report_payload)

        return jsonify({
            "status": "success",
            "product": "Love → Marriage Life Premium Report",
            "data": report,
        })

    except LoveServiceError as e:
        return jsonify({
            "status": "error",
            "error": str(e),
        }), 400

    except Exception:
        return jsonify({
            "status": "error",
            "error": "Unable to generate premium relationship report",
        }), 500
