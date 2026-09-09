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
from datetime import datetime, timezone
import logging
import traceback
import uuid

from extensions import db
from modules.user_service import get_or_create_app_user
from firebase_admin import auth as firebase_auth

# 🟢 Correct kundali calculator (confirmed by you)
from full_kundali_api import calculate_full_kundali

# U3B.1 -- the ONE authoritative extraction service. This route calls
# calculate_full_kundali() exactly once (below, unchanged) and hands
# the result to build_static_astrology_snapshot() -- it never
# re-implements Moon/Lagna/Nakshatra/Pada/Yog/Dosh extraction inline.
from modules.services.static_astrology_extractor import (
    build_static_astrology_snapshot,
    apply_snapshot_to_app_user,
)

# U4A.1 -- the same change-detection field list modules/user_service.py's
# own register_or_update_user() already uses (reused, not duplicated),
# and the ONE shared Dasha timeline service (modules/services/
# dasha_timeline_service.py) -- see the U4A.1 architecture decision for
# why this route needed its own before/after check added (it previously
# had none at all, unlike register_or_update_user()).
from modules.user_service import _ASTROLOGY_AFFECTING_FIELDS
from modules.services.dasha_timeline_service import sync_dasha_timeline_for_user

from modules.activity_events.service import record_event


routes_profile_bootstrap = Blueprint("routes_profile_bootstrap", __name__)

_activity_events_logger = logging.getLogger("activity_events")


def _emit_signup_completed(*, firebase_uid: str, app_user_id: int) -> None:
    """Phase 5D.1 -- observational only. Called ONLY after the caller's
    own AppUser creation has already durably committed (db.session.commit()
    already succeeded) AND only for the call that actually created that
    row (created == True) -- never for a routine bootstrap of an
    already-existing profile. This is the first durable creation of the
    Jyotishasha AppUser/profile, not merely a successful Firebase
    sign-in.

    No properties are sent: static inspection of this route found no
    already-existing, reliable, server-side authentication-provider
    value at this seam (the verified Firebase ID token's own claims do
    carry a provider, but nothing here currently reads it, and adding a
    new read solely to populate this event would be inventing a value
    the audit didn't find already in hand) -- signup_completed's frozen
    schema only makes `provider` optional, so an empty properties dict
    is valid and correct here, not a workaround.

    dedupe_key uses the just-created AppUser's own durable id -- not a
    fabricated identifier -- so a genuine duplicate emission attempt
    (never expected under the created-gate above, but defensive anyway)
    would be caught by the ledger's own partial unique index rather than
    ever producing a second row.

    Wrapped in its own try/except, mirroring routes_chat.py's
    _emit_asknow_event and entitlement_write_service.py's
    _emit_activity_event -- record_event() itself already never raises,
    but this defends against any error in the small amount of mapping
    logic below too, so an analytics failure can never propagate back
    into bootstrap_user_profile()'s already-successful response."""
    try:
        record_event(
            event_name="signup_completed",
            occurred_at=datetime.now(timezone.utc),
            platform="backend_internal",
            source="user_bootstrap",
            firebase_uid=firebase_uid,
            profile_id=app_user_id,
            entity_type=None,
            entity_id=None,
            correlation_id=None,
            session_id=None,
            properties={},
            dedupe_key=f"signup_completed:APP_USER:{app_user_id}",
        )
    except Exception:
        _activity_events_logger.warning(
            "routes_profile_bootstrap: unexpected error emitting "
            "signup_completed for AppUser.id=%s (swallowed -- the "
            "profile creation already committed successfully and is "
            "unaffected)",
            app_user_id, exc_info=True,
        )


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
        from modules.services.language_preference_service import content_language
        try:
            lang = content_language(data)
        except ValueError as exc:
            return jsonify(ok=False, error="invalid_language", message=str(exc)), 400

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

        # U3B.1 -- ONE extraction call from this SAME kundali result,
        # producing lagna/moon_sign/nakshatra/pada/yog/dosh together as
        # one internally-consistent snapshot (never a second
        # calculate_full_kundali() call, never a hand-rolled duplicate
        # of this extraction logic).
        static_astrology_snapshot = build_static_astrology_snapshot(kundali)
        lagna = static_astrology_snapshot["lagna"]
        moon_sign = static_astrology_snapshot["moon_sign"]
        nakshatra = static_astrology_snapshot["nakshatra"]

        print(f"[KUNDALI SUCCESS] trace_id={trace_id} lagna={lagna!r} "
              f"moon_sign={moon_sign!r} nakshatra={nakshatra!r}")

        # ----------------------------------------------------------
        # 2) Resolve (never create directly) the AppUser via the
        # single identity-resolution service from modules/user_service.py
        # ----------------------------------------------------------
        user, created = get_or_create_app_user(firebase_uid)

        print(f"[APPUSER] trace_id={trace_id} existing_or_new={'new' if created else 'existing'} "
              f"profile_id={user.id!r}")

        # U4A.1 -- before/after change detection for the Dasha timeline
        # ONLY (mirrors modules/user_service.py::register_or_update_user()'s
        # own _birth_details_changed check, reusing the same field list,
        # not a second definition). This route's EXISTING static-astrology
        # recalculation below is left exactly as it was -- unconditional,
        # every call -- since that is pre-existing behavior this task
        # does not change; only the NEW Dasha resync is gated, so a
        # repeated bootstrap call with identical birth data does not
        # delete-and-regenerate an unchanged 81-row timeline for nothing.
        _old_birth_details = tuple(getattr(user, f) for f in _ASTROLOGY_AFFECTING_FIELDS)

        user.name = name
        user.email = email
        user.dob = dob
        user.tob = tob
        user.pob = pob
        user.lat = lat
        user.lng = lng

        _new_birth_details = tuple(getattr(user, f) for f in _ASTROLOGY_AFFECTING_FIELDS)
        _birth_details_changed = _old_birth_details != _new_birth_details

        # Content language never changes authenticated app preference.

        # STORE personalized fields -- U3B.1: lagna/moon_sign/nakshatra
        # PLUS nakshatra_pada/static_yog/static_dosh/calculated_at/
        # version, all assigned together from the ONE snapshot above so
        # this profile can never end up with (e.g.) a new Moon Sign
        # paired with a stale Yog/Dosh -- see apply_snapshot_to_app_user().
        apply_snapshot_to_app_user(user, static_astrology_snapshot)

        # U4A.1 -- Dasha timeline resync, gated on the change-detection
        # above. sync_dasha_timeline_for_user() itself is unconditional
        # once called (it always deletes+rebuilds-or-invalidates); the
        # "don't touch it if nothing changed" decision belongs entirely
        # to this call site, exactly like register_or_update_user()'s
        # own gate. No commit happens inside the service -- staged into
        # this same session, committed once below with everything else.
        if _birth_details_changed:
            sync_dasha_timeline_for_user(user)
        print(f"[DASHA] trace_id={trace_id} birth_details_changed={_birth_details_changed}")

        print(f"[BEFORE COMMIT] trace_id={trace_id}")
        db.session.commit()
        print(f"[AFTER COMMIT] trace_id={trace_id} profile_id={user.id!r}")

        # Phase 5D.1 -- signup_completed: the first durable creation of
        # this AppUser/profile, emitted ONLY now that the commit above
        # has actually succeeded, and ONLY for the request that created
        # the row (created == True) -- never for a routine bootstrap of
        # an already-existing profile. Fire-and-forget, purely
        # observational: _emit_signup_completed() never raises, so it
        # cannot turn this already-successful response into an error,
        # and it runs strictly after -- never before or in place of --
        # the business commit it is reporting on.
        if created:
            _emit_signup_completed(firebase_uid=firebase_uid, app_user_id=user.id)

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
