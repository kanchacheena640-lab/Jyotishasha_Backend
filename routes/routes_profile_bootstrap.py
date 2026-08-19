"""
routes/routes_profile_bootstrap.py
----------------------------------
Personalized profile bootstrap route for Jyotishasha App.

This route:
1. Receives DOB, TOB, POB from the app
2. Runs calculate_full_kundali() from full_kundali_api.py
3. Extracts Lagna, Moon Sign, Nakshatra
4. Updates the AppUser resolved by modules.user_service.get_or_create_app_user()
5. Returns personalized profile JSON

This route never constructs AppUser() itself -- identity resolution is
owned exclusively by modules/user_service.py (ESR-001A/B), so this
route can never produce a second, disconnected AppUser row for a
person who already has one.
"""

from flask import Blueprint, request, jsonify
from datetime import datetime
import traceback
import uuid

from extensions import db
from modules.user_service import get_or_create_app_user
from firebase_admin import auth as firebase_auth

# 🟢 Correct kundali calculator (confirmed by you)
from full_kundali_api import calculate_full_kundali


routes_profile_bootstrap = Blueprint("routes_profile_bootstrap", __name__)


@routes_profile_bootstrap.post("/api/user/bootstrap")
def bootstrap_user_profile():
    # TEMPORARY DIAGNOSTIC INSTRUMENTATION -- structured logging only,
    # to trace exactly what this endpoint receives/writes/returns per
    # request while investigating the AppUser-missing-birth-fields
    # issue. No business logic, API contract, or database write below
    # was changed to add this -- every print() is purely additive.
    trace_id = uuid.uuid4().hex[:8]

    # Bucket A -- Critical Fix #3. This endpoint previously trusted
    # firebase_uid directly from the request body, with no proof the
    # caller actually owns that Firebase identity -- independently
    # verified as exploitable (a forged UID could overwrite another
    # user's profile/birth data or create a profile for a UID the
    # caller doesn't own). Fixed by reusing the exact same Firebase
    # verification pattern already used by
    # modules/auth/routes_profile.py::update_fcm_token() and
    # routes/routes_auth.py's register_user()/get_backend_token(). No
    # new authentication mechanism was introduced. Any firebase_uid the
    # client sends in the request body is now ignored entirely; the
    # UID used below always comes from the verified token.
    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Bearer "):
        return jsonify({"ok": False, "error": "Missing or invalid Authorization header"}), 401

    id_token = auth_header.replace("Bearer ", "").strip()

    try:
        decoded = firebase_auth.verify_id_token(id_token)
    except Exception:
        return jsonify({"ok": False, "error": "Invalid or expired Firebase token"}), 401

    firebase_uid = decoded.get("uid")
    if not firebase_uid:
        return jsonify({"ok": False, "error": "Invalid Firebase token"}), 401

    try:
        data = request.get_json() or {}

        print(f"[BOOTSTRAP START] trace_id={trace_id} firebase_uid={firebase_uid} "
              f"request_body_keys={list(data.keys())}")

        name = data.get("name")
        email = data.get("email")
        dob = data.get("dob")
        tob = data.get("tob")
        pob = data.get("pob")
        lat = data.get("lat")
        lng = data.get("lng")
        lang = data.get("lang", "en")

        print(f"[DOB CHECK] trace_id={trace_id} dob={dob!r} tob={tob!r} pob={pob!r} "
              f"lat={lat!r} lng={lng!r}")

        if not dob:
            return jsonify({"ok": False, "error": "DOB is required"}), 400

        # ----------------------------------------------------------
        # 1) Calculate Kundali
        # ----------------------------------------------------------
        kundali = calculate_full_kundali(
            name=name,
            dob=dob,
            tob=tob,
            lat=lat,
            lon=lng,
            language=lang,
        )

        lagna = kundali.get("lagna_sign")
        moon_sign = kundali.get("rashi")
        nakshatra = None

        for p in kundali.get("planets", []):
            if p["name"] == "Moon":
                nakshatra = p["nakshatra"]
                break

        print(f"[KUNDALI SUCCESS] trace_id={trace_id} lagna={lagna!r} "
              f"moon_sign={moon_sign!r} nakshatra={nakshatra!r}")

        # ----------------------------------------------------------
        # 2) Resolve (never create directly) the AppUser via the
        # single identity-resolution service from modules/user_service.py
        # ----------------------------------------------------------
        user, created = get_or_create_app_user(firebase_uid)

        print(f"[APPUSER] trace_id={trace_id} existing_or_new={'new' if created else 'existing'} "
              f"profile_id={user.id!r}")

        user.name = name
        user.email = email
        user.dob = dob
        user.tob = tob
        user.pob = pob
        user.lat = lat
        user.lng = lng

        # N3 -- persist the content-language preference this request
        # already carries (`lang`, used above only to render the kundali)
        # so downstream personalized-content notifications can read a real
        # per-user language instead of guessing. Only "en"/"hi" are
        # recognized; anything else is ignored rather than stored, leaving
        # the existing value (or NULL) untouched.
        if str(lang).strip().lower() in ("en", "hi"):
            user.lang = str(lang).strip().lower()

        # STORE personalized fields
        # (Your AppUser table MUST add these 3 columns)
        user.lagna = lagna
        user.moon_sign = moon_sign
        user.nakshatra = nakshatra

        print(f"[BEFORE COMMIT] trace_id={trace_id}")
        db.session.commit()
        print(f"[AFTER COMMIT] trace_id={trace_id} profile_id={user.id!r}")

        # ----------------------------------------------------------
        # 2b) Manual Trial Activation: this used to auto-provision the
        # initial free trial for a just-created profile here. That
        # auto-start is REMOVED by product decision -- a brand-new
        # profile is now intentionally left with no CurrentEntitlement
        # row (trial_available=True) until the user explicitly calls
        # POST /api/profile/activate-trial themselves. Nothing else
        # about this route's response/behavior changes.
        # ----------------------------------------------------------
        print(f"[TRIAL] trace_id={trace_id} created={bool(created)} "
              f"auto_trial_provisioning=disabled_by_product_decision")

        # ----------------------------------------------------------
        # 3) Response to App
        # ----------------------------------------------------------
        print(f"[RESPONSE] trace_id={trace_id} status=200 ok=True profile_id={user.id!r}")
        return jsonify({
            "ok": True,
            "profileId": user.id,
            "name": name,
            "dob": dob,
            "tob": tob,
            "pob": pob,
            "lagna": lagna,
            "moon_sign": moon_sign,
            "nakshatra": nakshatra,
        }), 200

    except Exception as e:
        print(f"[BOOTSTRAP EXCEPTION] trace_id={trace_id} "
              f"exception_type={type(e).__name__} exception_message={e}")
        print(traceback.format_exc())
        print("❌ Bootstrap Error:", e)
        return jsonify({"ok": False, "error": "Internal Server Error"}), 500
