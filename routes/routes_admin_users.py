# routes/routes_admin_users.py

"""
Users Module U2 -- real Admin Users API. Extended by U3A with
real (stored-only, never-recalculated) Birth Astrology filters, by
U3B.3 with stored-only Pada/Yog/Dosh filters + list/detail fields, by
U4A.3 with current Mahadasha/Antardasha filters + list/detail fields --
read ONLY from the persisted UserDashaTimeline, never a Dasha
calculation, never a write -- and by U4B.2 with Sade Sati
active/phase filters + list/detail fields, derived from persisted
AppUser.moon_sign + ONE current Saturn sign resolved per request (see
modules/services/admin_users_service.py's own SadeSatiUnavailableError
handling below -- a resolution failure returns a clear 503, never a
fabricated active=false/null), and by U4C.3 with current-transit-house
filters (jupiter_house/saturn_house/rahu_house/ketu_house) + a full
9-planet current_transits detail section, derived from persisted
AppUser.lagna + ONE current transit snapshot resolved per request (see
admin_users_service.py's own TransitUnavailableError handling below --
same 503-on-failure contract as Sade Sati's, never a fabricated null/
incorrect result). This file still never imports
get_moon_longitude_lahiri()/calculate_vimshottari_dasha()/swisseph/
transit_engine/smart_transit_engine or any other astrology-calculation
function directly.

Two endpoints only, both gated by the existing, already-proven
admin_or_bridge_required decorator (routes_app_version.py) -- REUSED
unmodified, not duplicated: it accepts either the Next.js Admin BFF's
X-Admin-Bridge-Key secret or a real admin JWT (admin_required's own
ADMIN_USER_IDS check), exactly like /api/app/version-policy's PATCH.

Audience saving remains out of scope. This file never imports
calculate_full_kundali() or any individual Yog/Dosh evaluator --
Pada/Yog/Dosh here are exclusively U3B.1's already-stored app_users
columns, read through modules/services/admin_users_service.py's
existing correlated-bridge pattern.

U5A -- Ask Now concern intelligence is now real: a THIRD endpoint,
GET /admin/api/users/asknow-concerns (same admin_or_bridge_required
gate), exposes the currently active category names from the existing
DB-backed master (never hardcoded here or in the frontend); the list
endpoint gains an ask_now_concern filter (comma-separated category
names, validated against that same active set, read-only EXISTS
against ask_now_intent_history -- never a calculation, never a write);
and the detail endpoint gains a `ask_now` section (buyer/total
classified question count/concern history, category+source+timestamp
only -- never the raw question/answer text, which is never persisted
anywhere in this codebase to begin with). Category management
(add/enable/disable) is explicitly NOT exposed here -- see
modules/services/asknow_category_service.py's own add_category()/
set_category_active(), unused by this file.
"""

from flask import Blueprint, jsonify, request

from routes.routes_app_version import admin_or_bridge_required
from modules.services.admin_users_service import (
    CANONICAL_DASHA_LORDS,
    CANONICAL_NAKSHATRAS,
    CANONICAL_NAKSHATRA_PADAS,
    CANONICAL_SADE_SATI_PHASES,
    CANONICAL_SIGNS,
    CANONICAL_TRANSIT_HOUSES,
    FILTERABLE_TRANSIT_PLANETS,
    SadeSatiUnavailableError,
    TransitUnavailableError,
    get_user_detail,
    get_users_summary,
    list_users,
)
from modules.services.static_astrology_extractor import (
    CANONICAL_DOSH_KEYS,
    CANONICAL_YOG_KEYS,
)
# U5A -- the ONE authoritative source of CURRENTLY ACTIVE Ask Now
# concern-category names (modules/models_ask_now_concern_category.py's
# DB-backed master, U5.0's frozen discovery). Read-only here -- this
# file never calls add_category()/set_category_active() (Section 17:
# category management is explicitly out of scope for this task).
from modules.services.asknow_category_service import get_active_category_names

routes_admin_users = Blueprint("routes_admin_users", __name__)

_VALID_STATUSES = ("active", "inactive", "unknown")
_VALID_CUSTOMER_TYPES = ("free", "paying")
_CANONICAL_SIGNS_SET = set(CANONICAL_SIGNS)
_CANONICAL_NAKSHATRAS_SET = set(CANONICAL_NAKSHATRAS)
_CANONICAL_NAKSHATRA_PADAS_SET = set(CANONICAL_NAKSHATRA_PADAS)
_CANONICAL_DASHA_LORDS_SET = set(CANONICAL_DASHA_LORDS)
_CANONICAL_SADE_SATI_PHASES_SET = set(CANONICAL_SADE_SATI_PHASES)
# U4C.3 -- houses are always exactly 1-12 (see admin_users_service.py's
# own CANONICAL_TRANSIT_HOUSES docstring).
_CANONICAL_TRANSIT_HOUSES_SET = set(CANONICAL_TRANSIT_HOUSES)


def _parse_bool(raw):
    """None (param absent) is preserved distinctly from an explicit
    false -- "no filter" and "filter for false" are different queries."""
    if raw is None:
        return None
    return str(raw).strip().lower() in ("1", "true", "yes")


def _parse_int(raw):
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _parse_multi(raw):
    """U3A -- a comma-separated multi-select value, e.g.
    "Aries,Taurus" -> ["Aries", "Taurus"]. None (not an empty list) when
    the param is absent/blank, matching every other optional filter
    here -- "no filter" must stay distinguishable from "filter matches
    nothing"."""
    if not raw:
        return None
    values = [v.strip() for v in raw.split(",") if v.strip()]
    return values or None


def _parse_multi_int(raw):
    """U3B.3 -- a comma-separated multi-select of INTEGER values, e.g.
    "1,2" -> [1, 2]. Raises ValueError for any non-integer token (e.g.
    "abc", "2.5") -- the caller turns that into a clean 400, never
    silently drops the bad token."""
    if not raw:
        return None
    values = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        values.append(int(token))  # ValueError for "abc" / "2.5"
    return values or None


def _parse_transit_house_param(raw, param_name):
    """U4C.3 -- shared parsing/validation for jupiter_house/saturn_house/
    rahu_house/ketu_house: comma-separated integers, each must be one of
    CANONICAL_TRANSIT_HOUSES (1-12) -- exactly the same
    _parse_multi_int()-then-subset-check shape nakshatra_pada above
    already uses, factored into one helper since there are 4 near-
    identical instances of it here. "0", "13", "abc", "1.5" all reject
    with 400, matching this file's existing invalid-filter convention
    exactly. Returns (parsed_list_or_None, error_response_dict_or_None)
    -- the caller returns (jsonify(error), 400) when error is not None."""
    try:
        values = _parse_multi_int(raw)
    except ValueError:
        return None, {
            "error": f"invalid_{param_name}",
            "message": f"{param_name} values must be integers, one of {CANONICAL_TRANSIT_HOUSES}.",
        }
    if values and not set(values).issubset(_CANONICAL_TRANSIT_HOUSES_SET):
        return None, {
            "error": f"invalid_{param_name}",
            "message": f"{param_name} values must be a subset of {CANONICAL_TRANSIT_HOUSES}.",
        }
    return values, None


@routes_admin_users.route("/admin/api/users/asknow-concerns", methods=["GET"])
@admin_or_bridge_required
def admin_asknow_concerns():
    """U5A -- Category Discovery API (Section 2). Returns ONLY the
    CURRENTLY ACTIVE Ask Now concern-category names, straight from the
    existing DB-backed master (modules/services/asknow_category_service.py
    ::get_active_category_names() -- the SAME function chat_engine.py
    itself calls at generation time, so this can never drift from what
    Luna is actually classifying against). Read-only: this route never
    calls add_category()/set_category_active() (Section 17 -- category
    management is out of scope here). Gated by the SAME admin_or_bridge_
    required decorator as every other route in this file -- no public
    unauthenticated access.

    Route is registered UNDER /admin/api/users/ specifically so it is
    tried before the /admin/api/users/<int:user_id> detail route below
    -- Flask's <int:...> converter never matches a non-numeric segment
    like "asknow-concerns", so no route-ordering ambiguity actually
    exists, but the path itself is deliberately self-documenting either
    way."""
    try:
        categories = get_active_category_names()
    except Exception:
        # Same explicit-failure posture as Sade Sati's/Transit's own
        # resolution-failure contract elsewhere in this file -- never a
        # silently empty category list (which would look, to the Admin
        # frontend, exactly like "zero categories are currently active,"
        # a fabrication of a fact we don't actually have).
        return jsonify({"error": "asknow_concern_unavailable"}), 503
    return jsonify({"categories": categories}), 200


@routes_admin_users.route("/admin/api/users", methods=["GET"])
@admin_or_bridge_required
def admin_list_users():
    args = request.args
    language = None
    if "language" in args:
        values = args.get("language").split(",")
        if len(args.getlist("language")) != 1 or not values or any(v not in ("en", "hi") for v in values):
            return jsonify(error="invalid_language"), 400
        language = sorted(set(values))


    status = (args.get("status") or "").strip() or None
    if status is not None and status not in _VALID_STATUSES:
        return jsonify({
            "error": "invalid_status",
            "message": f"status must be one of {_VALID_STATUSES}.",
        }), 400

    customer_type = (args.get("customer_type") or "").strip() or None
    if customer_type is not None and customer_type not in _VALID_CUSTOMER_TYPES:
        return jsonify({
            "error": "invalid_customer_type",
            "message": f"customer_type must be one of {_VALID_CUSTOMER_TYPES}.",
        }), 400

    moon_sign = _parse_multi(args.get("moon_sign"))
    if moon_sign and not set(moon_sign).issubset(_CANONICAL_SIGNS_SET):
        return jsonify({
            "error": "invalid_moon_sign",
            "message": f"moon_sign values must be a subset of {CANONICAL_SIGNS}.",
        }), 400

    lagna = _parse_multi(args.get("lagna"))
    if lagna and not set(lagna).issubset(_CANONICAL_SIGNS_SET):
        return jsonify({
            "error": "invalid_lagna",
            "message": f"lagna values must be a subset of {CANONICAL_SIGNS}.",
        }), 400

    nakshatra = _parse_multi(args.get("nakshatra"))
    if nakshatra and not set(nakshatra).issubset(_CANONICAL_NAKSHATRAS_SET):
        return jsonify({
            "error": "invalid_nakshatra",
            "message": f"nakshatra values must be a subset of {CANONICAL_NAKSHATRAS}.",
        }), 400

    try:
        nakshatra_pada = _parse_multi_int(args.get("nakshatra_pada"))
    except ValueError:
        return jsonify({
            "error": "invalid_nakshatra_pada",
            "message": f"nakshatra_pada values must be integers, one of {CANONICAL_NAKSHATRA_PADAS}.",
        }), 400
    if nakshatra_pada and not set(nakshatra_pada).issubset(_CANONICAL_NAKSHATRA_PADAS_SET):
        return jsonify({
            "error": "invalid_nakshatra_pada",
            "message": f"nakshatra_pada values must be a subset of {CANONICAL_NAKSHATRA_PADAS}.",
        }), 400

    yog = _parse_multi(args.get("yog"))
    if yog and not set(yog).issubset(CANONICAL_YOG_KEYS):
        return jsonify({
            "error": "invalid_yog",
            "message": f"yog values must be a subset of {sorted(CANONICAL_YOG_KEYS)}.",
        }), 400

    dosh = _parse_multi(args.get("dosh"))
    if dosh and not set(dosh).issubset(CANONICAL_DOSH_KEYS):
        return jsonify({
            "error": "invalid_dosh",
            "message": f"dosh values must be a subset of {sorted(CANONICAL_DOSH_KEYS)}.",
        }), 400

    # U4A.3 -- current Mahadasha/Antardasha filters, read-only against
    # the persisted UserDashaTimeline (see admin_users_service.py --
    # never a calculation, never a write).
    mahadasha = _parse_multi(args.get("mahadasha"))
    if mahadasha and not set(mahadasha).issubset(_CANONICAL_DASHA_LORDS_SET):
        return jsonify({
            "error": "invalid_mahadasha",
            "message": f"mahadasha values must be a subset of {CANONICAL_DASHA_LORDS}.",
        }), 400

    antardasha = _parse_multi(args.get("antardasha"))
    if antardasha and not set(antardasha).issubset(_CANONICAL_DASHA_LORDS_SET):
        return jsonify({
            "error": "invalid_antardasha",
            "message": f"antardasha values must be a subset of {CANONICAL_DASHA_LORDS}.",
        }), 400

    # U4B.2 -- Sade Sati filters, read-only against persisted
    # AppUser.moon_sign + the one current Saturn sign resolved per
    # request (see admin_users_service.py) -- never a calculation,
    # never a write. sade_sati_active reuses the SAME lenient boolean
    # convention _parse_bool() already gives ask_now_buyer/
    # active_subscription (no existing boolean filter in this file
    # rejects an invalid value with a 400; this one is deliberately
    # kept consistent with that, not stricter).
    sade_sati_active = _parse_bool(args.get("sade_sati_active"))

    sade_sati_phase = _parse_multi(args.get("sade_sati_phase"))
    if sade_sati_phase and not set(sade_sati_phase).issubset(_CANONICAL_SADE_SATI_PHASES_SET):
        return jsonify({
            "error": "invalid_sade_sati_phase",
            "message": f"sade_sati_phase values must be a subset of {CANONICAL_SADE_SATI_PHASES}.",
        }), 400

    # U4C.3 -- current-transit-house filters for the 4 v1-scoped bodies
    # (see admin_users_service.py's own FILTERABLE_TRANSIT_PLANETS).
    # Read-only, derived from persisted AppUser.lagna + the one current
    # transit snapshot resolved (lazily, at most once) inside
    # list_users() itself -- never a calculation here, never a write.
    jupiter_house, _err = _parse_transit_house_param(args.get("jupiter_house"), "jupiter_house")
    if _err:
        return jsonify(_err), 400
    saturn_house, _err = _parse_transit_house_param(args.get("saturn_house"), "saturn_house")
    if _err:
        return jsonify(_err), 400
    rahu_house, _err = _parse_transit_house_param(args.get("rahu_house"), "rahu_house")
    if _err:
        return jsonify(_err), 400
    ketu_house, _err = _parse_transit_house_param(args.get("ketu_house"), "ketu_house")
    if _err:
        return jsonify(_err), 400

    # U5A -- Ask Now Concern filter. Comma-separated category NAMES
    # (never a machine key/id -- the category master's own `name` column
    # is the identity, see modules/models_ask_now_concern_category.py),
    # validated against the CURRENTLY ACTIVE set only (Section 4's
    # explicit contract: an inactive-but-historically-real category name
    # is rejected with 400 here, exactly like a never-existed name --
    # the filter UI contract is "what can I ask for today," not "what
    # ever existed"). A genuine failure reading the category master
    # (DB down, table missing) is indistinguishable from Sade Sati's/
    # Transit's own resolution-failure contract -- same explicit 503,
    # never a silently-accepted or silently-dropped filter.
    ask_now_concern = _parse_multi(args.get("ask_now_concern"))
    if ask_now_concern:
        try:
            active_categories = set(get_active_category_names())
        except Exception:
            return jsonify({"error": "asknow_concern_unavailable"}), 503
        if not set(ask_now_concern).issubset(active_categories):
            return jsonify({
                "error": "invalid_ask_now_concern",
                "message": f"ask_now_concern values must be a subset of the currently active categories: {sorted(active_categories)}.",
            }), 400

    page = max(1, _parse_int(args.get("page")) or 1)
    page_size = _parse_int(args.get("page_size")) or 20

    try:
        result = list_users(
            search=(args.get("search") or "").strip() or None,
            age_min=_parse_int(args.get("age_min")),
            age_max=_parse_int(args.get("age_max")),
            status=status,
            signup_from=(args.get("signup_from") or "").strip() or None,
            signup_to=(args.get("signup_to") or "").strip() or None,
            customer_type=customer_type,
            ask_now_buyer=_parse_bool(args.get("ask_now_buyer")),
            active_subscription=_parse_bool(args.get("active_subscription")),
            moon_sign=moon_sign,
            lagna=lagna,
            nakshatra=nakshatra,
            nakshatra_pada=nakshatra_pada,
            yog=yog,
            dosh=dosh,
            mahadasha=mahadasha,
            antardasha=antardasha,
            sade_sati_active=sade_sati_active,
            sade_sati_phase=sade_sati_phase,
            jupiter_house=jupiter_house,
            saturn_house=saturn_house,
            rahu_house=rahu_house,
            ketu_house=ketu_house,
            ask_now_concern=ask_now_concern,
            language=language,
            page=page,
            page_size=page_size,
        )
    except SadeSatiUnavailableError:
        # U4B.2 Section 4 -- a Saturn-resolution failure must NEVER be
        # reported as active=false or silently as null (both would be a
        # fabrication) -- this is the one clear, explicit signal a
        # caller can distinguish from every other response shape.
        return jsonify({"error": "sade_sati_unavailable"}), 503
    except TransitUnavailableError:
        # U4C.3 Section 13 -- a current-transit-snapshot resolution
        # failure (only possible when at least one of jupiter_house/
        # saturn_house/rahu_house/ketu_house was requested -- see
        # list_users()'s own lazy-resolution docstring) must NEVER be
        # silently reported as "no users match" -- the one clear,
        # explicit signal a caller can distinguish from a genuinely
        # empty result set.
        return jsonify({"error": "transit_unavailable"}), 503

    return jsonify({
        "summary": get_users_summary(),
        "users": result["users"],
        "pagination": result["pagination"],
    }), 200


@routes_admin_users.route("/admin/api/users/<int:user_id>", methods=["GET"])
@admin_or_bridge_required
def admin_get_user_detail(user_id):
    try:
        detail = get_user_detail(user_id)
    except SadeSatiUnavailableError:
        return jsonify({"error": "sade_sati_unavailable"}), 503
    except TransitUnavailableError:
        # U4C.3 -- get_user_detail() always resolves the current
        # transit snapshot (User Detail's 9-planet section is never
        # opt-in) -- a failure here must never silently return a
        # null/incorrect current_transits section.
        return jsonify({"error": "transit_unavailable"}), 503
    if detail is None:
        return jsonify({"error": "not_found", "message": "No user with this id."}), 404
    return jsonify(detail), 200
