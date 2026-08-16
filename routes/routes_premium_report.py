# routes/routes_premium_report.py

"""
Premium Report API (Phase 6, revised in Phase 7, hardened in S4.0).

Phase 7 moved every business decision out of this controller and into
PremiumReportService (modules/premium_report/). This file does three
things:
    1. Parse the HTTP request.
    2. Verify the caller owns the profile being requested (S4.0).
    3. Call PremiumReportService.get_report().
    4. Translate whatever PremiumReportError it catches into an HTTP
       response, using that exception's own status_code/error_code --
       this controller never inspects exception text or `.__cause__`
       chains itself (that translation lives entirely inside the
       service).

S4.0 -- Backend Hardening: this endpoint previously trusted `profile_id`
directly from an unauthenticated query string (S3 audit finding,
High). PremiumReportService's own entitlement check
(validate_entitlement_access) already verified the requested profile
had access to the requested segment, but nothing verified the CALLER
was that profile's owner -- ownership and entitlement are distinct
concerns. Fixed by reusing the project's existing, already-proven
pattern for exactly this situation -- @jwt_required() +
get_jwt_identity() + resolve_profile_id_from_account_user_id()
(modules/subscription/dual_write_adapter.py) -- the same three calls
already used by modules/auth/routes_profile.py::subscription_info()
and routes/routes_google_purchase_confirm.py. No new authentication
mechanism was introduced, and PremiumReportService itself is
untouched: ownership is verified here, in the controller, before the
service is ever called. `profile_id` in the query string remains
optional and, if present, is only ever compared against the
authenticated identity's own resolved profile_id -- a mismatch is
rejected (403) as a cross-account attempt, never silently substituted
or trusted. Every entitlement check PremiumReportService already
performed (validate_entitlement_access -- trial/subscription/segment
access) is preserved exactly as it was.
"""

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from modules.premium_report import PremiumReportError, PremiumReportService
from modules.subscription.dual_write_adapter import (
    resolve_profile_id_from_account_user_id,
)

premium_report_bp = Blueprint("premium_report", __name__)

# Bilingual Contract fix -- smallest backward-compatible language
# normalization at the API boundary. Previously `language` was taken
# verbatim from the query string with no validation at all: any
# arbitrary string flowed straight through to the generator/prompt
# chain. Downstream, every prompt builder's own `_language_instruction()`
# already treats anything other than the literal string "hi" as English
# (never as "invalid Hindi") -- so this normalization does not change
# any generation behavior, it only makes the API boundary itself
# explicit and robust to casing/whitespace ("HI", " hi ", "Hi" all now
# correctly resolve to Hindi, matching user intent, instead of silently
# falling through to English with no indication why). A genuinely
# unsupported value (e.g. "fr", "xx") is never treated as Hindi -- it
# safely normalizes to "en", the same default this endpoint already had.
SUPPORTED_LANGUAGES = ("en", "hi")


def _normalize_language(raw_language: str) -> str:
    normalized = (raw_language or "en").strip().lower()
    return normalized if normalized in SUPPORTED_LANGUAGES else "en"


@premium_report_bp.route("/api/premium-report", methods=["GET"])
@jwt_required()
def get_premium_report():
    # S4.0 -- ownership validation. The authenticated account's own
    # profile_id is resolved from the JWT identity and is always the
    # value actually used below; a client-supplied profile_id (if any)
    # is only ever checked for a match, never trusted on its own.
    user_id = get_jwt_identity()
    authenticated_profile_id = resolve_profile_id_from_account_user_id(user_id)
    if authenticated_profile_id is None:
        return jsonify({
            "error": "forbidden", "message": "No profile is associated with this account.",
        }), 403

    profile_id_raw = request.args.get("profile_id")
    segment = request.args.get("segment")
    report_type = request.args.get("report_type")
    language = _normalize_language(request.args.get("language", "en"))

    if profile_id_raw is not None:
        try:
            requested_profile_id = int(profile_id_raw)
        except ValueError:
            return jsonify({"error": "invalid_request", "message": "profile_id must be an integer."}), 400
        if requested_profile_id != authenticated_profile_id:
            return jsonify({
                "error": "forbidden",
                "message": "profile_id does not belong to the authenticated account.",
            }), 403

    profile_id = authenticated_profile_id

    service = PremiumReportService()

    try:
        result = service.get_report(
            current_user_id=authenticated_profile_id,
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
