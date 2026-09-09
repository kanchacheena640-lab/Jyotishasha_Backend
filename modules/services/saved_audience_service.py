# modules/services/saved_audience_service.py

"""
U6A -- Saved Audience CRUD + preview service.

Frozen U6.0 architecture: dynamic/criteria-based, users.id-scoped, no
membership persistence, no second filter/astrology engine. Every
membership-resolving function here (`preview_audience`,
`preview_criteria`) delegates straight to modules/services/
admin_users_service.py::list_users() -- the SAME function GET
/admin/api/users itself calls -- so Saved Audience preview and the live
Admin Users list can never define membership differently for identical
criteria.
"""

from datetime import datetime

from extensions import db
from modules.models_saved_audience import SavedAudience
from modules.services.saved_audience_criteria import validate_criteria, CriteriaValidationError
from modules.services.admin_users_service import (
    list_users,
    SadeSatiUnavailableError,
    TransitUnavailableError,
)

# Re-exported so callers (routes) only need to import this one module
# for both the service functions and the exception types they must
# catch -- avoids every route importing from 3 different modules for
# one request handler.
__all__ = [
    "create_audience", "update_audience", "deactivate_audience",
    "get_audience", "list_audiences", "preview_audience", "preview_criteria",
    "AudienceNotFoundError", "CriteriaValidationError",
    "SadeSatiUnavailableError", "TransitUnavailableError",
]


class AudienceNotFoundError(LookupError):
    """Raised when a SavedAudience id does not exist. The route layer
    turns this into a 404, matching get_user_detail()'s own "None ->
    404, never a fabricated empty audience" convention."""


def create_audience(*, name: str, description: str = None, criteria: dict, created_by: int = None) -> SavedAudience:
    """Validates `criteria` with authoring=True (Section 10 -- requires
    every ask_now_concern value to be a CURRENTLY ACTIVE category) and
    persists a new row. Raises CriteriaValidationError (never a bare
    exception) for any invalid name/criteria -- never partially writes
    a row for invalid input."""
    name = (name or "").strip()
    if not name:
        raise CriteriaValidationError("invalid_name", "name must not be blank.")

    validated_filters = validate_criteria(criteria, authoring=True)
    # Store criteria EXACTLY as validated (version + the validated
    # filters dict) -- never the raw, unvalidated input verbatim, so a
    # criteria object that happened to pass with extra ignored fields
    # (there are none possible here, since validate_criteria() already
    # rejects any key outside {"version","filters"}) can never diverge
    # from what was actually checked.
    stored_criteria = {"version": criteria["version"], "filters": validated_filters}

    audience = SavedAudience(
        name=name,
        description=(description or None),
        criteria=stored_criteria,
        created_by=created_by,
        is_active=True,
    )
    db.session.add(audience)
    db.session.commit()
    return audience


def update_audience(
    audience_id: int, *, name: str = None, description: str = None,
    criteria: dict = None, is_active: bool = None,
) -> SavedAudience:
    """PATCH semantics for name/description/is_active (only the fields
    actually supplied are changed) -- but criteria, if supplied, is a
    COMPLETE REPLACEMENT, fully re-validated with authoring=True, never
    a partial/merged filter object (Section 14 -- merging a malformed
    partial criteria object with a previously-valid one could silently
    produce a combination that was never itself validated as a whole)."""
    audience = SavedAudience.query.get(audience_id)
    if audience is None:
        raise AudienceNotFoundError(f"No SavedAudience with id={audience_id}")

    if name is not None:
        name = name.strip()
        if not name:
            raise CriteriaValidationError("invalid_name", "name must not be blank.")
        audience.name = name

    if description is not None:
        audience.description = description or None

    if criteria is not None:
        validated_filters = validate_criteria(criteria, authoring=True)
        audience.criteria = {"version": criteria["version"], "filters": validated_filters}

    if is_active is not None:
        audience.is_active = bool(is_active)

    audience.updated_at = datetime.utcnow()
    db.session.commit()
    return audience


def deactivate_audience(audience_id: int) -> SavedAudience:
    """Soft-deactivate only (Section 12/17) -- never a physical DELETE.
    Idempotent: deactivating an already-inactive audience is a no-op
    success, not an error."""
    audience = SavedAudience.query.get(audience_id)
    if audience is None:
        raise AudienceNotFoundError(f"No SavedAudience with id={audience_id}")
    audience.is_active = False
    audience.updated_at = datetime.utcnow()
    db.session.commit()
    return audience


def get_audience(audience_id: int) -> SavedAudience:
    audience = SavedAudience.query.get(audience_id)
    if audience is None:
        raise AudienceNotFoundError(f"No SavedAudience with id={audience_id}")
    return audience


def list_audiences(*, is_active: bool = None) -> list:
    """Lightweight metadata list (Section 15) -- NEVER resolves any
    audience's membership/count here. `is_active=None` returns every
    audience (active and inactive both remain readable in Admin --
    Section 21); pass True/False to filter."""
    query = SavedAudience.query
    if is_active is not None:
        query = query.filter(SavedAudience.is_active == is_active)
    return query.order_by(SavedAudience.created_at.desc()).all()


def preview_criteria(criteria: dict, *, page: int = 1, page_size: int = 20) -> dict:
    """U6A Section 19 -- direct-criteria preview (no saved row needed
    yet). authoring=True: matches the exact same validation an eventual
    create_audience() call with this same criteria would apply, so
    "preview looks fine" and "save succeeds" can never disagree. Reuses
    list_users() -- the SAME resolver GET /admin/api/users itself calls
    -- for both the paginated preview rows and the CURRENT (never
    cached) member_count. Raises CriteriaValidationError/
    SadeSatiUnavailableError/TransitUnavailableError -- the route layer
    maps each to its own structured response."""
    filters = validate_criteria(criteria, authoring=True)
    result = list_users(**filters, page=page, page_size=page_size)
    return {
        "member_count": result["pagination"]["total_count"],
        "users": result["users"],
        "pagination": result["pagination"],
    }


def preview_audience(audience_id: int, *, page: int = 1, page_size: int = 20) -> dict:
    """U6A Section 17 -- preview an EXISTING saved audience. Section 21:
    previewing an INACTIVE audience is explicitly ALLOWED (preview is
    read-only Admin inspection, never an action) -- `is_active` is never
    checked here. authoring=False: an ask_now_concern category that
    became inactive after this audience was saved must NOT block
    resolution (U6.0/Section 10/11) -- only structural/type/canonical-
    set validation runs here, as a defense-in-depth re-check of
    already-once-validated stored criteria, never a live "still active"
    re-check.

    member_count is CALCULATED fresh from list_users()'s own
    total_count on every call -- never read from a stored/cached field
    (none exists on this model by design, see modules/models_saved_
    audience.py's own docstring) -- so preview always reflects today's
    Dasha/Sade Sati/Transit/subscription/activity state."""
    audience = get_audience(audience_id)
    filters = validate_criteria(audience.criteria, authoring=False)
    result = list_users(**filters, page=page, page_size=page_size)
    return {
        "audience": audience.to_dict(),
        "member_count": result["pagination"]["total_count"],
        "users": result["users"],
        "pagination": result["pagination"],
    }
