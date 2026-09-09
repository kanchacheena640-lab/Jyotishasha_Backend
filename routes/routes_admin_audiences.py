# routes/routes_admin_audiences.py

"""
U6A -- Saved Audience CRUD + preview API.

Gated by the SAME admin_or_bridge_required decorator every other Admin
Users route already uses (routes_app_version.py) -- accepts either the
Next.js Admin BFF's X-Admin-Bridge-Key secret or a real admin JWT
(admin_required's own ADMIN_USER_IDS check). No new auth mechanism.

created_by (Section 5) -- audited BOTH real admin authentication paths
before implementing this:
  - Admin JWT path: admin_required() already runs @jwt_required() (hard)
    before this file's own handler executes, so a real, already-verified
    users.id identity is available via get_jwt_identity().
  - Bridge-key path (X-Admin-Bridge-Key, the Next.js Admin BFF's own
    server-to-server call): admin_or_bridge_required() short-circuits
    BEFORE admin_required()/@jwt_required() ever runs -- there is no
    JWT on the request at all, and therefore no admin identity to read.
_resolve_admin_identity() below reflects this precisely: it returns a
real users.id ONLY when a real JWT was actually verified on this
request, and None otherwise -- created_by is NULL for every bridge-key-
authenticated request, which is the valid, expected, non-fabricated
outcome (see modules/models_saved_audience.py's own docstring). No
AdminUser identity system is introduced here.

Endpoints:
  GET    /admin/api/audiences                 -- lightweight metadata list
  POST   /admin/api/audiences                 -- create
  GET    /admin/api/audiences/<id>            -- metadata + criteria
  PATCH  /admin/api/audiences/<id>             -- name/description/criteria/is_active
  DELETE /admin/api/audiences/<id>            -- soft-deactivate (is_active=false), never a physical delete
  GET    /admin/api/audiences/<id>/preview    -- resolve an EXISTING saved audience
  POST   /admin/api/audiences/preview          -- resolve criteria BEFORE saving

This file never imports get_moon_longitude_lahiri()/
calculate_vimshottari_dasha()/swisseph/transit_engine/smart_transit_engine
or personalization_engine.get_users_for_transit() -- every membership
resolution goes through modules/services/admin_users_service.py::
list_users(), the SAME function GET /admin/api/users itself calls.
"""

from flask import Blueprint, jsonify, request
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity

from routes.routes_app_version import admin_or_bridge_required
from modules.services.saved_audience_criteria import CriteriaValidationError
from modules.services.saved_audience_service import (
    create_audience,
    update_audience,
    deactivate_audience,
    get_audience,
    list_audiences,
    preview_audience,
    preview_criteria,
    AudienceNotFoundError,
    SadeSatiUnavailableError,
    TransitUnavailableError,
)

routes_admin_audiences = Blueprint("routes_admin_audiences", __name__)


def _resolve_admin_identity():
    """Best-effort resolution of the calling admin's own users.id, for
    SavedAudience.created_by (Section 5, see this module's own
    docstring for the full path audit). Returns None whenever no real
    admin JWT was presented on this request -- the valid, expected
    outcome for the bridge-key path. Mirrors routes/routes_chat.py's own
    _resolve_gated_user_id() pattern (verify_jwt_in_request(optional=True),
    never raising for "no JWT present")."""
    try:
        verify_jwt_in_request(optional=True)
        identity = get_jwt_identity()
        return int(identity) if identity is not None else None
    except Exception:
        return None


def _parse_int(raw, default=None):
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _criteria_error_response(exc: CriteriaValidationError):
    return jsonify({"error": exc.code, "message": str(exc)}), 400


@routes_admin_audiences.route("/admin/api/audiences", methods=["GET"])
@admin_or_bridge_required
def admin_list_audiences():
    """Section 15 -- lightweight metadata only. Never resolves any
    audience's membership/count here (that would trigger repeated
    dynamic-astrology work, once per row, on every list page load)."""
    args = request.args
    is_active = None
    raw_is_active = args.get("is_active")
    if raw_is_active is not None:
        is_active = str(raw_is_active).strip().lower() in ("1", "true", "yes")

    audiences = list_audiences(is_active=is_active)
    return jsonify({"audiences": [a.to_dict() for a in audiences]}), 200


@routes_admin_audiences.route("/admin/api/audiences", methods=["POST"])
@admin_or_bridge_required
def admin_create_audience():
    data = request.get_json(silent=True) or {}
    name = data.get("name")
    description = data.get("description")
    criteria = data.get("criteria")

    if criteria is None:
        return jsonify({"error": "invalid_criteria", "message": "criteria is required."}), 400

    try:
        audience = create_audience(
            name=name, description=description, criteria=criteria,
            created_by=_resolve_admin_identity(),
        )
    except CriteriaValidationError as exc:
        return _criteria_error_response(exc)

    return jsonify(audience.to_dict()), 201


@routes_admin_audiences.route("/admin/api/audiences/<int:audience_id>", methods=["GET"])
@admin_or_bridge_required
def admin_get_audience(audience_id):
    """Section 16 -- stored metadata + criteria only. Never returns
    thousands of member user IDs here -- use .../preview for that."""
    try:
        audience = get_audience(audience_id)
    except AudienceNotFoundError:
        return jsonify({"error": "not_found", "message": "No audience with this id."}), 404
    return jsonify(audience.to_dict()), 200


@routes_admin_audiences.route("/admin/api/audiences/<int:audience_id>", methods=["PATCH"])
@admin_or_bridge_required
def admin_update_audience(audience_id):
    data = request.get_json(silent=True) or {}
    # Distinguish "field not supplied" (None -- leave unchanged) from
    # "field explicitly supplied" using the sentinel-free `in data`
    # check, so a PATCH that omits `description` never accidentally
    # clears it, matching this task's own PATCH-not-PUT semantics.
    kwargs = {}
    if "name" in data:
        kwargs["name"] = data["name"]
    if "description" in data:
        kwargs["description"] = data["description"]
    if "criteria" in data:
        kwargs["criteria"] = data["criteria"]
    if "is_active" in data:
        kwargs["is_active"] = data["is_active"]

    try:
        audience = update_audience(audience_id, **kwargs)
    except AudienceNotFoundError:
        return jsonify({"error": "not_found", "message": "No audience with this id."}), 404
    except CriteriaValidationError as exc:
        return _criteria_error_response(exc)

    return jsonify(audience.to_dict()), 200


@routes_admin_audiences.route("/admin/api/audiences/<int:audience_id>", methods=["DELETE"])
@admin_or_bridge_required
def admin_deactivate_audience(audience_id):
    """Section 12/21 -- SOFT-deactivate only (is_active=false). The row
    and its criteria are never physically removed -- an Admin can still
    read/reactivate it later via PATCH {"is_active": true}."""
    try:
        audience = deactivate_audience(audience_id)
    except AudienceNotFoundError:
        return jsonify({"error": "not_found", "message": "No audience with this id."}), 404
    return jsonify(audience.to_dict()), 200


@routes_admin_audiences.route("/admin/api/audiences/<int:audience_id>/preview", methods=["GET"])
@admin_or_bridge_required
def admin_preview_audience(audience_id):
    """Section 17 -- resolves an EXISTING saved audience's CURRENT
    membership, via the exact same list_users() GET /admin/api/users
    itself calls. Previewing an INACTIVE audience is explicitly allowed
    (Section 21 -- preview is read-only inspection, never an action)."""
    page = max(1, _parse_int(request.args.get("page"), 1))
    page_size = _parse_int(request.args.get("page_size"), 20)

    try:
        result = preview_audience(audience_id, page=page, page_size=page_size)
    except AudienceNotFoundError:
        return jsonify({"error": "not_found", "message": "No audience with this id."}), 404
    except CriteriaValidationError as exc:
        return _criteria_error_response(exc)
    except SadeSatiUnavailableError:
        return jsonify({"error": "sade_sati_unavailable"}), 503
    except TransitUnavailableError:
        return jsonify({"error": "transit_unavailable"}), 503

    return jsonify(result), 200


@routes_admin_audiences.route("/admin/api/audiences/preview", methods=["POST"])
@admin_or_bridge_required
def admin_preview_criteria():
    """Section 19 -- direct-criteria preview, BEFORE an audience is ever
    saved (future frontend flow: set filters -> see member count ->
    save). Applies the SAME authoring-time validation create_audience()
    would apply, so a criteria object that previews successfully is
    guaranteed to also save successfully."""
    data = request.get_json(silent=True) or {}
    criteria = data.get("criteria")
    if criteria is None:
        return jsonify({"error": "invalid_criteria", "message": "criteria is required."}), 400

    page = max(1, _parse_int(data.get("page"), 1))
    page_size = _parse_int(data.get("page_size"), 20)

    try:
        result = preview_criteria(criteria, page=page, page_size=page_size)
    except CriteriaValidationError as exc:
        return _criteria_error_response(exc)
    except SadeSatiUnavailableError:
        return jsonify({"error": "sade_sati_unavailable"}), 503
    except TransitUnavailableError:
        return jsonify({"error": "transit_unavailable"}), 503

    return jsonify(result), 200
