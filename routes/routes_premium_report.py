# routes/routes_premium_report.py

"""
Premium Report API (Phase 6, revised in Phase 7).

Phase 7 moved every business decision out of this controller and into
PremiumReportService (modules/premium_report/). This file now does
ONLY three things:
    1. Parse the HTTP request.
    2. Call PremiumReportService.get_report().
    3. Translate whatever PremiumReportError it catches into an HTTP
       response, using that exception's own status_code/error_code --
       this controller never inspects exception text or `.__cause__`
       chains itself anymore (that translation lives entirely inside
       the service now).

No subscription check, no auth change, no Flutter change -- the
service's access-control hooks are placeholders that always allow
access this phase (see PremiumReportService for where those will
attach later).
"""

from flask import Blueprint, jsonify, request

from modules.premium_report import PremiumReportError, PremiumReportService

premium_report_bp = Blueprint("premium_report", __name__)


@premium_report_bp.route("/api/premium-report", methods=["GET"])
def get_premium_report():
    profile_id_raw = request.args.get("profile_id")
    segment = request.args.get("segment")
    report_type = request.args.get("report_type")
    language = request.args.get("language", "en")

    profile_id = None
    if profile_id_raw is not None:
        try:
            profile_id = int(profile_id_raw)
        except ValueError:
            return jsonify({"error": "invalid_request", "message": "profile_id must be an integer."}), 400

    service = PremiumReportService()

    try:
        result = service.get_report(
            # No authentication exists yet -- current_user_id is not
            # available, so it's passed through as None. Once auth
            # exists, this becomes the authenticated user's id and
            # nothing else in this controller needs to change.
            current_user_id=None,
            profile_id=profile_id,
            segment=segment,
            report_type=report_type,
            language=language,
        )
    except PremiumReportError as exc:
        return jsonify({"error": exc.error_code, "message": exc.public_message}), exc.status_code
    except Exception:
        return jsonify({"error": "internal_error", "message": "Unexpected failure."}), 500

    return jsonify(result), 200
