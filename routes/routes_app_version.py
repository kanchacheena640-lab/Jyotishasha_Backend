# routes/routes_app_version.py

"""
Force-Update / Minimum-Supported-Build Policy API.

    GET  /api/app/version-policy   -- public, no auth (a client that must
                                       be told to update cannot be required
                                       to authenticate to learn that)
    PATCH /admin/api/app-version-policy -- admin-gated (reuses
                                       admin_required, the same JWT +
                                       ADMIN_USER_IDS allowlist every other
                                       admin-only route in this codebase
                                       already uses) -- the mechanism this
                                       task's Part F requires: changing
                                       minimum_supported_build WITHOUT
                                       shipping a new app version.

Read model: modules/models_app_version_policy.py::AppVersionPolicy,
one row per platform (only "android" exists today). This route never
creates a row -- that only happens via the seeding migration
(migrations/versions/<...>_add_app_version_policy_table.py); GET on a
platform with no row is a structured 404 tail-fast, not a 500 and not a
guessed default -- a version gate that fails to explain itself is worse
than one that fails open (see the Flutter client's own fail-open
posture for the matching client-side half of this contract).
"""

from __future__ import annotations

import hmac
import os
from functools import wraps

from flask import Blueprint, jsonify, request

from extensions import db
from modules.models_app_version_policy import AppVersionPolicy
from notifications.notification_routes import admin_required

routes_app_version = Blueprint("routes_app_version", __name__)

_SUPPORTED_PLATFORMS = ("android",)


def _bridge_key_valid(provided: str | None) -> bool:
    """
    Narrow, additive credential for exactly one caller: the Next.js
    Admin BFF route (server-side only -- never reaches a browser). Not
    a replacement for admin_required, not usable on any other route.

    Deny-by-default: an unset/empty ADMIN_BRIDGE_SECRET means this path
    can never succeed, so a fresh/local environment behaves exactly as
    it did before this existed. Constant-time compare -- same reasoning
    as the Next.js admin session signature check this mirrors.
    """
    expected = os.getenv("ADMIN_BRIDGE_SECRET", "")
    if not expected or not provided:
        return False
    return hmac.compare_digest(provided, expected)


def admin_or_bridge_required(fn):
    """
    Accepts EITHER credential, tried in this order:
      1. X-Admin-Bridge-Key -- the Next.js Admin BFF's server-side
         secret (see _bridge_key_valid above).
      2. The existing admin_required JWT + ADMIN_USER_IDS check,
         completely unmodified -- this is the fallback for every
         existing caller and every existing test, so a request with no
         (or a wrong) bridge key behaves byte-for-byte as it always
         has: 401 with no Authorization header, 403 for a non-admin
         identity.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if _bridge_key_valid(request.headers.get("X-Admin-Bridge-Key")):
            return fn(*args, **kwargs)
        return admin_required(fn)(*args, **kwargs)
    return wrapper


@routes_app_version.route("/api/app/version-policy", methods=["GET"])
def get_version_policy():
    # Only "android" is a real platform today (this app has no iOS
    # build) -- an unrecognized value is a structured 400, not a silent
    # fallback to "android" that would hide a client-side typo.
    platform = (request.args.get("platform") or "android").strip().lower()
    if platform not in _SUPPORTED_PLATFORMS:
        return jsonify({
            "error": "unsupported_platform",
            "message": f"platform must be one of {_SUPPORTED_PLATFORMS!r}.",
        }), 400

    policy = AppVersionPolicy.query.filter_by(platform=platform).first()
    if policy is None:
        # No policy has ever been seeded for this platform -- reported,
        # never guessed. The Flutter client's fail-open posture already
        # treats any non-2xx (including this) as "do not block."
        return jsonify({
            "error": "no_policy_configured",
            "message": f"No version policy exists for platform={platform!r}.",
        }), 404

    return jsonify(policy.to_public_dict()), 200


@routes_app_version.route("/admin/api/app-version-policy", methods=["PATCH"])
@admin_or_bridge_required
def update_version_policy():
    """
    Operator-only update -- the ONLY way minimum_supported_build/
    force_update/latest_build/store_url/message change, other than the
    one-time seed migration. Every field is optional; only fields
    actually present in the request body are touched, so a caller
    raising minimum_supported_build alone never has to also re-supply
    store_url/message unchanged.
    """
    platform = (request.args.get("platform") or "android").strip().lower()
    if platform not in _SUPPORTED_PLATFORMS:
        return jsonify({
            "error": "unsupported_platform",
            "message": f"platform must be one of {_SUPPORTED_PLATFORMS!r}.",
        }), 400

    policy = AppVersionPolicy.query.filter_by(platform=platform).first()
    if policy is None:
        return jsonify({
            "error": "no_policy_configured",
            "message": f"No version policy exists for platform={platform!r}. "
                       f"Seed one via migration before updating it.",
        }), 404

    data = request.get_json(silent=True) or {}

    if "minimum_supported_build" in data:
        try:
            policy.minimum_supported_build = int(data["minimum_supported_build"])
        except (TypeError, ValueError):
            return jsonify({
                "error": "invalid_field",
                "message": "minimum_supported_build must be an integer.",
            }), 400

    if "latest_build" in data:
        try:
            policy.latest_build = int(data["latest_build"])
        except (TypeError, ValueError):
            return jsonify({
                "error": "invalid_field",
                "message": "latest_build must be an integer.",
            }), 400

    # Reusable App Update System (Task H) -- cross-field invariant.
    # Checked AFTER both individual fields are applied (in-memory, not
    # yet committed) so this catches every path to an inconsistent
    # state: raising minimum past the current latest, lowering latest
    # below the current minimum, or setting both in the same request.
    # A rejected request leaves the previously-committed row completely
    # untouched -- db.session.commit() below is never reached.
    if policy.minimum_supported_build > policy.latest_build:
        # Cosmetic-message fix: capture the rejected candidate values
        # BEFORE rollback(). Session.rollback() expires every tracked
        # instance, so reading policy.* after it re-SELECTs from the DB
        # and would silently report the previous committed values
        # instead of the values that were actually rejected.
        candidate_minimum = policy.minimum_supported_build
        candidate_latest = policy.latest_build
        db.session.rollback()
        return jsonify({
            "error": "invalid_policy",
            "message": (
                f"minimum_supported_build ({candidate_minimum}) "
                f"cannot exceed latest_build ({candidate_latest})."
            ),
        }), 400

    if "force_update" in data:
        if not isinstance(data["force_update"], bool):
            return jsonify({
                "error": "invalid_field",
                "message": "force_update must be a boolean.",
            }), 400
        policy.force_update = data["force_update"]

    if "store_url" in data:
        store_url = data["store_url"]
        if not isinstance(store_url, str) or not store_url.strip():
            return jsonify({
                "error": "invalid_field",
                "message": "store_url must be a non-empty string.",
            }), 400
        policy.store_url = store_url.strip()

    if "message" in data:
        message = data["message"]
        if message is not None and not isinstance(message, str):
            return jsonify({
                "error": "invalid_field",
                "message": "message must be a string or null.",
            }), 400
        policy.message = message

    db.session.commit()

    return jsonify(policy.to_public_dict()), 200
