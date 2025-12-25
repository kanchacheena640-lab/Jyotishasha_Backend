from __future__ import annotations

from flask import Blueprint, request, jsonify

from modules.love.service_love import run_love_compatibility, LoveServiceError
from modules.love.love_report_compiler import compile_love_report
from modules.love.truth_or_dare_compiler import compile_truth_or_dare
from full_kundali_api import calculate_full_kundali
from modules.love.love_marriage_probability_compiler import compile_love_marriage_probability





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

@love_bp.route("/report", methods=["POST"])
def love_report():
    payload = request.get_json(silent=True) or {}
    user = payload.get("user") or {}
    partner = payload.get("partner") or {}

    if _is_blank(user.get("name")) or _is_blank(user.get("dob")):
        return jsonify({
            "ok": False,
            "error": "USER_DOB_REQUIRED",
            "message": "User name and date of birth are required."
        }), 400

    if _is_blank(partner.get("name")) or _is_blank(partner.get("dob")):
        return jsonify({
            "ok": False,
            "error": "PARTNER_DOB_REQUIRED",
            "message": "Partner name and date of birth are required."
        }), 400

    try:
        # 1️⃣ Base compatibility (data only)
        base_result = run_love_compatibility(
            user=user,
            partner=partner,
            boy_is_user=payload.get("boy_is_user", True),
        )

        # 2️⃣ Compiler payload (LOCKED structure)
        report_payload = {
            "language": payload.get("language", "en"),
            "client": user,
            **base_result,
        }

        # 3️⃣ Final paid report
        final_report = compile_love_report(report_payload)

        return jsonify({
            "ok": True,
            "data": final_report,
        }), 200

    except LoveServiceError as e:
        return jsonify({
            "ok": False,
            "error": "LOVE_SERVICE_ERROR",
            "message": str(e),
        }), 400

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": "INTERNAL_ERROR",
            "message": "Internal server error",
        }), 500

@love_bp.route("/truth-or-dare", methods=["POST"])
def love_truth_or_dare():
    payload = request.get_json(silent=True) or {}
    user = payload.get("user") or {}
    partner = payload.get("partner") or {}

    # Basic validation
    if _is_blank(user.get("name")) or _is_blank(user.get("dob")):
        return jsonify({
            "ok": False,
            "error": "USER_DOB_REQUIRED",
            "message": "User name and date of birth are required."
        }), 400

    if _is_blank(partner.get("name")) or _is_blank(partner.get("dob")):
        return jsonify({
            "ok": False,
            "error": "PARTNER_DOB_REQUIRED",
            "message": "Partner name and date of birth are required."
        }), 400

    try:
        # ------------------------------------------------
        # 1) Reuse existing love compatibility logic
        # ------------------------------------------------
        base_result = run_love_compatibility(
            user=user,
            partner=partner,
            boy_is_user=payload.get("boy_is_user", True),
        )

        case = base_result.get("case")

        # ------------------------------------------------
        # 2) Build kundali payloads (as available)
        # ------------------------------------------------
        kundali_user = {}

        # Build full kundali ONLY if full birth details are available
        if (
            user.get("tob")
            and user.get("lat") is not None
            and user.get("lng") is not None
        ):
            kundali_user = calculate_full_kundali(
                name=user["name"],
                dob=user["dob"],
                tob=user["tob"],
                lat=user["lat"],
                lon=user["lng"],
                language=payload.get("language", "en"),
            )

        kundali_partner = {}
        if case == "A_FULL_DUAL":
            kundali_partner = calculate_full_kundali(
                name=partner["name"],
                dob=partner["dob"],
                tob=partner.get("tob"),
                lat=partner.get("lat"),
                lon=partner.get("lng"),
                language=payload.get("language", "en"),
            )

        # ------------------------------------------------
        # 3) Compiler payload (LOCKED)
        # ------------------------------------------------
        compiler_payload = {
            "language": payload.get("language", "en"),
            "case": case,
            "user": user,
            "partner": partner,
            "kundali_user": kundali_user,
            "kundali_partner": kundali_partner,
        }

        # ------------------------------------------------
        # 4) Compile Truth-or-Dare result
        # ------------------------------------------------
        result = compile_truth_or_dare(compiler_payload)

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
    
@love_bp.route("/love-marriage-probability", methods=["POST"])
def love_marriage_probability():
    payload = request.get_json(silent=True) or {}
    user = payload.get("user") or {}
    partner = payload.get("partner") or {}

    if _is_blank(user.get("name")) or _is_blank(user.get("dob")):
        return jsonify({
            "ok": False,
            "error": "USER_DOB_REQUIRED",
            "message": "User name and date of birth are required."
        }), 400

    if _is_blank(partner.get("name")) or _is_blank(partner.get("dob")):
        return jsonify({
            "ok": False,
            "error": "PARTNER_DOB_REQUIRED",
            "message": "Partner name and date of birth are required."
        }), 400

    try:
        # Build kundalis only when full details exist
        lang = payload.get("language", "en")

        # USER kundali (full only)
        kundali_user = {}
        if user.get("tob") and user.get("lat") is not None and user.get("lng") is not None:
            kundali_user = calculate_full_kundali(
                name=user["name"],
                dob=user["dob"],
                tob=user["tob"],
                lat=user["lat"],
                lon=user["lng"],
                language=lang,
            )

        # PARTNER kundali (full only)
        kundali_partner = {}
        if partner.get("tob") and partner.get("lat") is not None and partner.get("lng") is not None:
            kundali_partner = calculate_full_kundali(
                name=partner["name"],
                dob=partner["dob"],
                tob=partner["tob"],
                lat=partner["lat"],
                lon=partner["lng"],
                language=lang,
            )

        # Case
        case = "A_FULL_DUAL" if (kundali_user and kundali_partner) else "B_DOB_ONLY_HYBRID"

        compiler_payload = {
            "language": lang,
            "case": case,
            "user": user,
            "partner": partner,
            "chart_data_user": (
                kundali_user.get("chart_data")
                if kundali_user else {}
            ),
            "chart_data_partner": (
                kundali_partner.get("chart_data")
                if kundali_partner else {}
            ),
        }

        out = compile_love_marriage_probability(compiler_payload)

        return jsonify({"ok": True, "data": out}), 200

    except Exception:
        return jsonify({
            "ok": False,
            "error": "INTERNAL_ERROR",
            "message": "Internal server error",
        }), 500

