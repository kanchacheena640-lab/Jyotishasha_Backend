# modules/services/admin_users_service.py

"""
Users Module U2 -- real-data aggregation for /admin/users.

Canonical identity: users.id (Users Module U2 audit's own locked
decision). users.id is NEVER assumed equal to app_users.id -- every
profile-scoped fact (subscription entitlement) is reached through the
existing, already-proven bridge:

    users.firebase_uid -> app_users.firebase_uid -> app_users.id (profile_id)

...via a correlated subquery (_entitlement_plan_expr / _entitlement_status_expr
below), never a naive users.id == app_users.id join. A users.id row with
firebase_uid IS NULL correctly yields NULL for every bridged fact --
never fabricated, never silently treated as "no subscription" in a way
that's indistinguishable from "bridge unavailable".

Locked U2 business rules (see the U2 discovery/verification audits this
implements):

  ACTIVE STATUS (redefined, U2.1 Data Enrichment audit)
    last_active_at = MAX(activity_events.occurred_at) matched by
    users.firebase_uid directly (no bridge needed -- firebase_uid is a
    real column on `users` itself), RESTRICTED to event_name ==
    "session_start" (ACTIVE_EVENT_NAME below) -- the one canonical,
    Flutter-emitted, backend-identity-verified app-open-equivalent event
    (Phase 5B: fired at most once per Dart process, from SplashPage's
    returning-user cold start or LoginPage's fresh sign-in). Locked U2.1
    rule: "Active User = a user who OPENED THE APP within the last 30
    days" -- an Ask Now purchase, subscription event, report purchase,
    or any other activity_events row must NOT by itself make a user
    Active. Before this change, ANY event_name counted; that is exactly
    the behavior this redefinition removes.

      unknown  -- firebase_uid IS NULL, OR firebase_uid is set but no
                  session_start row exists at all (this now also covers
                  a user who is genuinely engaged via other events --
                  Ask Now, payments, subscriptions -- but has never
                  produced a session_start; per the locked rule, that is
                  an honest "unknown", never a fabricated "active").
                  NEVER reported as inactive -- a locked, explicit rule.
      active   -- last session_start within the last 30 days.
      inactive -- firebase_uid known, a session_start exists, but not
                  within 30 days.

    Coverage caveat (see U2.1 report, section 1): session_start
    instrumentation shipped only a few days before this change (app
    build 1.1.5+50). Real historical coverage is still ramping up as
    users update and relaunch -- expect a temporary bulge of "unknown"
    users until then. This is the honest, non-fabricated outcome the
    unknown/active/inactive model is explicitly designed for, not a bug.

  PAYING
    ask_now_buyer      = a GENUINELY PAID, successfully verified ChatPack
                         purchase exists for this users.id (a lifetime
                         "ever purchased" fact, not "currently has
                         questions left") -- U5A CORRECTION: status=='success'
                         alone is NOT sufficient, because the SAME table
                         also carries two known non-purchase "success"
                         rows: ad-reward mini-packs (razorpay_order_id ==
                         "REWARD_AD", amount == 0) and admin support
                         grants (razorpay_order_id == "ADMIN_ADD", amount
                         == 51 -- a POSITIVE amount, so amount > 0 alone
                         would NOT have excluded this one). See
                         _ask_now_buyer_expr()'s own docstring below for
                         the exact predicate and the full purchase-path
                         audit behind it (U5.0/U5A).
    subscription payer = CurrentEntitlement.plan IS NOT NULL, reached
                         via the firebase_uid bridge (plan is documented
                         on CurrentEntitlement itself as "None while on
                         trial / never purchased").
    customer_type = "paying" if EITHER is true, else "free".
    Order/report-purchase email matching is explicitly EXCLUDED (no
    reliable account linkage exists for that table -- see the U2
    discovery audit, reaffirmed by the U2.1 Purchased Reports audit).
    UNCHANGED by U2.1 -- Paying's definition is explicitly out of scope
    for this task.

  ACTIVE SUBSCRIPTION
    CurrentEntitlement.status IN ('ACTIVE', 'GRACE'). TRIAL is
    deliberately excluded -- a trial is not a paid active subscription.

  AGE (U2.1 Data Enrichment audit -- DOB source fixed)
    Resolved with this precedence, each step validated against the
    exact YYYY-MM-DD shape before being trusted:
      1. users.dob (the canonical dashboard identity's own birth-detail
         field) -- used as-is if present and validly shaped.
      2. Otherwise, the bridged app_users.dob reached via the SAME
         firebase_uid bridge every other profile-scoped fact in this
         file already uses (_app_user_id_bridge_expr and friends) --
         never users.id == app_users.id, never email/phone matching.
         app_users.firebase_uid is a PARTIAL UNIQUE index (WHERE
         firebase_uid IS NOT NULL -- modules/models_user.py), so this
         bridge can never resolve to more than one AppUser row.
      3. If neither source has a validly-shaped DOB, age is SQL NULL
         (and JSON null) -- a genuine, never-fabricated data anomaly.

  BIRTH ASTROLOGY (U3A -- Moon Sign / Lagna / Nakshatra)
    Reused, never recalculated: moon_sign/lagna/nakshatra are read
    directly from the bridged app_users row (same firebase_uid bridge
    as DOB above) -- these are static profile facts already computed
    once by full_kundali_api.py::calculate_full_kundali() at profile
    bootstrap time (routes/routes_profile_bootstrap.py) and persisted.
    This module NEVER imports or calls calculate_full_kundali() or any
    other astrology-engine function -- U3's own discovery audit is
    explicit that Admin must never recalculate a Kundali per list/
    filter/detail request. NULL whenever the bridge can't be completed
    OR the linked profile has never had these fields populated -- never
    fabricated, never a placeholder like "Unknown". Filter values are
    validated against the SAME canonical English enums the engine
    itself uses (CANONICAL_SIGNS / CANONICAL_NAKSHATRAS below, imported
    from full_kundali_api.py's own SIGNS/NAKSHATRAS constants -- not a
    second, potentially-drifting copy).

  STATIC PADA / YOG / DOSH (U3B.3 -- reads ONLY U3B.1's stored columns)
    nakshatra_pada/static_yog/static_dosh/static_astrology_calculated_at/
    static_astrology_version are read directly from the bridged
    app_users row -- the SAME U3B.1 persistence written once by
    routes_profile_bootstrap.py/modules/user_service.py/the U3B.2
    backfill script. This module still never imports or calls
    calculate_full_kundali() or any individual Yog/Dosh evaluator.

    Calculated/uncalculated/empty semantics (frozen, never blurred):
      - static_astrology_calculated_at IS NULL -> NOT CALCULATED. List
        response: nakshatra_pada/active_yog/active_dosh/
        static_astrology_calculated_at are all JSON null. Detail
        response: static_yog/static_dosh are JSON null. NEVER reported
        as `[]`/`{}` -- that would falsely claim "calculated, nothing
        active/present" for a profile that was never calculated at all.
      - static_astrology_calculated_at IS NOT NULL -> CALCULATED.
        static_yog/static_dosh are the stored JSONB object, `{}` when
        calculated but nothing is active/present. List response reduces
        this to active_yog/active_dosh -- flat arrays of the sparse
        JSONB object's own keys (e.g. `["gajakesari_yog"]`), computed
        in Python at serialization time from the already-fetched JSONB
        value (not a second query, not a filter -- see list_users()'s
        own docstring for why SQL-level filtering is unaffected by this).
        Detail response exposes the full stored JSONB verbatim -- no
        prose, no reasons/positives/challenge/description/remedies/
        upsell (never stored there to begin with, see
        modules/services/static_astrology_extractor.py).

    Filter values (nakshatra_pada/yog/dosh) are validated against:
      - nakshatra_pada: the fixed set {1, 2, 3, 4} (Pada has no other
        possible value, see static_astrology_extractor.py's own
        get_nakshatra_pada() contract).
      - yog/dosh: CANONICAL_YOG_KEYS / CANONICAL_DOSH_KEYS, imported
        directly from static_astrology_extractor.py -- the ONE
        authoritative registry (derived there from the same private
        constants the extractor's own persistence logic uses), never a
        second hand-copied list, never derived from frontend mock data.

    JSONB filtering: Postgres key-presence (`?`) / any-of (`?|`)
    operators via SQLAlchemy's JSONB comparator (`.has_key()`/
    `.has_any()`), applied directly to the bridged correlated scalar
    subquery -- executed entirely in SQL, before pagination, exactly
    like every other filter in this file. Postgres's own NULL semantics
    already give the correct "never matches" behavior for an
    uncalculated (NULL) or empty (`{}`) document with zero special-
    casing needed: `NULL ?| array[...]` and `'{}'::jsonb ?| array[...]`
    both evaluate to NULL/false, never true.

No N+1 queries: every per-user fact above is expressed as a correlated
SQL subquery/expression evaluated by Postgres as part of ONE query for
the whole page (or ONE query per summary count) -- never a Python loop
issuing one extra query per row.
"""

from datetime import datetime, timedelta
import math

from sqlalchemy import and_, case, cast, func, literal, or_
from sqlalchemy.dialects.postgresql import ARRAY, TEXT, array as pg_array

from extensions import db
from modules.auth.models import User
from modules.models_user import AppUser, UserDashaTimeline
from modules.models_chat_pack import ChatPack
from modules.models_ask_now_intent_history import AskNowIntentHistory
from modules.models_premium_subscription import CurrentEntitlement
from modules.models_activity_events import ActivityEvent
# U3A -- reusing the astrology engine's OWN canonical value lists for
# filter validation only (a plain import of two constant lists, never a
# call into the engine itself; full_kundali_api is already resident in
# every running process via ~50 other importers, so this adds no new
# module-load cost). Aliased to make the "these are the engine's real
# enums, not a second hand-copied list" intent explicit at the call site.
# U4A.3 -- DASHA_SEQUENCE reused the same way for the Mahadasha/
# Antardasha lord filter validation below -- this file still never
# calls calculate_vimshottari_dasha()/get_moon_longitude_lahiri() or
# any other Dasha CALCULATION function, only reads its own frozen list
# of the 9 possible lord names.
from full_kundali_api import (
    SIGNS as _ENGINE_SIGNS,
    NAKSHATRAS as _ENGINE_NAKSHATRAS,
    DASHA_SEQUENCE as _ENGINE_DASHA_SEQUENCE,
)
# U3B.3 -- the ONE authoritative Yog/Dosh machine-key registry (already
# derived, in static_astrology_extractor.py itself, from the same
# private constants its own persistence logic uses -- never a second,
# independently-typed list here).
from modules.services.static_astrology_extractor import (
    CANONICAL_YOG_KEYS,
    CANONICAL_DOSH_KEYS,
)
# U4B.2 -- the ONE authoritative Sade Sati rule (U4B.1) and current-
# Saturn resolver. This file NEVER imports get_moon_longitude_lahiri(),
# calculate_vimshottari_dasha(), calculate_full_kundali(), swisseph, or
# smart_transit_engine/transit_engine directly -- resolve_current_saturn_sign()
# is the ONLY sanctioned way this module ever learns "what sign is
# Saturn in right now", and classify_sade_sati() is the ONLY sanctioned
# way it ever turns a (moon_sign, saturn_sign) pair into active/phase.
from services.sadhesati_classifier import (
    classify_sade_sati,
    PHASE_FIRST,
    PHASE_SECOND,
    PHASE_THIRD,
    STATE_ACTIVE,
)
from services.current_saturn_resolver import resolve_current_saturn_sign
# U4C.3 -- the ONE canonical current-transit-house rule
# (services/personalization_engine.py::calculate_house(), already
# proven identical to modules/smartchat/chart_summarizer.py's own
# _rashi_to_house() for all 144 Lagna x transit-sign combinations in
# U4C.0's audit) and the ONE canonical current-positions resolver
# (services/current_transit_resolver.py, itself a thin wrapper over
# transit_engine.get_current_positions() -- U4C.0-U4C.2B's frozen,
# Lahiri-thread-safe canonical transit engine). This file still never
# imports swisseph, transit_engine, or smart_transit_engine directly --
# calculate_house() and resolve_current_transit_snapshot() are the ONLY
# sanctioned ways it ever learns "what house is a planet currently
# transiting" / "what sign is a planet currently in".
from services.personalization_engine import calculate_house
from services.current_transit_resolver import (
    resolve_current_transit_snapshot,
    TRACKED_PLANETS as TRANSIT_TRACKED_PLANETS,
)

ACTIVE_SUBSCRIPTION_STATUSES = ("ACTIVE", "GRACE")
LAST_ACTIVE_WINDOW_DAYS = 30

# U2.1 -- the ONLY event_name that can ever set last_active_at/status
# now that "Active" means "opened the app," not "did anything at all."
# See modules/activity_events/event_schemas.py's EVENT_SCHEMAS registry
# (Section I, "Core") and the Flutter producer at
# lib/core/analytics/session_start_producer.dart (jyotishasha_appF) --
# fired at most once per Dart process, from an already-authenticated
# seam only, with firebase_uid/profile_id resolved server-side from the
# caller's JWT (never client-supplied) by the ingestion pipeline.
ACTIVE_EVENT_NAME = "session_start"

# Exact YYYY-MM-DD shape only -- anything else (empty string, "0000-00-00"
# style garbage, free text) is treated as "no usable DOB", never guessed.
_DOB_SHAPE_RE = r"^\d{4}-\d{2}-\d{2}$"

MAX_PAGE_SIZE = 200

# U3A -- the exact, canonical set of values app_users.moon_sign/lagna
# (12 signs) and app_users.nakshatra (27 nakshatras) can ever legally
# hold, because these are the only values full_kundali_api.py's own
# SIGNS/NAKSHATRAS arrays can ever produce. Used ONLY to validate
# incoming filter values (routes_admin_users.py) -- never to constrain
# what a stored value can be (a stored value is trusted as-is; this is
# purely "is this filter request even askable").
CANONICAL_SIGNS = tuple(_ENGINE_SIGNS)
CANONICAL_NAKSHATRAS = tuple(_ENGINE_NAKSHATRAS)

# U3B.3 -- Pada has exactly 4 possible values by construction (see
# static_astrology_extractor.py / full_kundali_api.py::get_nakshatra_pada()),
# never anything else.
CANONICAL_NAKSHATRA_PADAS = (1, 2, 3, 4)

# U4A.3 -- the exact, canonical set of values UserDashaTimeline.mahadasha/
# antardasha can ever legally hold, because these are the only lord
# names full_kundali_api.py's own DASHA_SEQUENCE can ever produce (U4A.0
# verified this list -- Ketu/Venus/Sun/Moon/Mars/Rahu/Jupiter/Saturn/
# Mercury -- and its 120-year-cycle math directly). Used ONLY to
# validate incoming filter values (routes_admin_users.py), exactly like
# CANONICAL_SIGNS/CANONICAL_NAKSHATRAS above.
CANONICAL_DASHA_LORDS = tuple(_ENGINE_DASHA_SEQUENCE)

# U4B.2 -- the exact 3 canonical Sade Sati phase strings, reused from
# services/sadhesati_classifier.py's own constants (never hand-copied
# literals) -- used ONLY to validate incoming sade_sati_phase filter
# values (routes_admin_users.py).
CANONICAL_SADE_SATI_PHASES = (PHASE_FIRST, PHASE_SECOND, PHASE_THIRD)

# U4C.3 -- houses are always exactly 1-12 by construction of the
# canonical house formula itself (calculate_house() below can only ever
# return one of these 12 integers, or None) -- used ONLY to validate
# incoming jupiter_house/saturn_house/rahu_house/ketu_house filter
# values (routes_admin_users.py).
CANONICAL_TRANSIT_HOUSES = tuple(range(1, 13))

# U4C.3 -- the 4 slower-moving bodies Admin can FILTER audiences by
# (Section 3's explicit v1 scope: Jupiter/Saturn/Rahu/Ketu only -- fast
# movers would create excessive short-lived filter dimensions). User
# Detail exposes all 9 TRANSIT_TRACKED_PLANETS regardless -- this tuple
# is filter-scope only.
FILTERABLE_TRANSIT_PLANETS = ("Jupiter", "Saturn", "Rahu", "Ketu")


class TransitUnavailableError(RuntimeError):
    """Raised by list_users()/get_user_detail() when
    resolve_current_transit_snapshot() itself fails for a request that
    needs current-transit-house data (list: only when at least one of
    jupiter_house/saturn_house/rahu_house/ketu_house was requested;
    detail: unconditionally, since User Detail always exposes all 9
    current transit bodies). Mirrors SadeSatiUnavailableError's own
    invariant exactly: a transit-resolution failure must NEVER be
    silently reported as an empty/null result (that would fabricate a
    confident "no users match"/"no current transit data" answer from a
    fact we don't actually have) -- the route layer MUST turn this into
    an explicit 503/service-unavailable response."""


class SadeSatiUnavailableError(RuntimeError):
    """Raised by list_users()/get_user_detail() when
    resolve_current_saturn_sign() itself fails for a request that needs
    Sade Sati data (every list/detail request, per U4B.2's contract --
    sade_sati_active/sade_sati_phase are unconditional response fields,
    not opt-in). The route layer MUST turn this into an explicit
    503/service-unavailable response.

    THE KEY INVARIANT THIS EXISTS TO PROTECT: a Saturn-resolution
    failure must NEVER be silently reported as active=false (that would
    fabricate a confident "genuinely inactive" answer from a fact we
    don't actually have) and must NEVER be silently reported as
    active=null the same way a missing Moon sign is (that would make an
    infrastructure failure indistinguishable from NOT_CALCULATED, an
    honest per-profile data fact). Both would be a fabrication -- this
    exception exists so callers see the failure and only the failure."""


# ---------------------------------------------------------------------
# Reusable expression builders -- the SAME functions back both
# list_users() and get_user_detail(), so the business rules above have
# exactly one implementation, never two definitions that could drift.
# ---------------------------------------------------------------------

# U5A -- Ask Now Buyer Correctness Fix. Full ChatPack creation/payment
# path audit (repository-verified, not assumed) before this predicate
# was written:
#
#   GENUINE purchase paths (both set status="success" ONLY after real
#   provider verification, both always a POSITIVE amount, both always a
#   real provider-issued razorpay_order_id/razorpay_payment_id):
#     - Razorpay: chat_pack_service.py::create_chatpack_order() creates
#       a "pending" row with a REAL Razorpay order id; ::
#       verify_chatpack_payment() flips it to "success" only after a
#       real RazorpayProvider() HMAC signature verification. amount is
#       always CHATPACK_AMOUNT=51.
#     - Google Play: chatpack_google_verify.py::verify_google_chatpack()
#       creates the row directly at status="success", but ONLY after a
#       real GooglePlayProvider().verify_product_purchase() call
#       confirms VERIFIED + purchase_state==Purchased. razorpay_order_id
#       is Google's own real order_id, or the literal fallback
#       f"GP_{product_id}" ONLY when Google didn't return one (still a
#       genuine purchase -- never a sentinel). amount is 51 (asknow8q) or
#       100 (asknow10q), from CHATPACK_PRODUCT_MAP -- always positive.
#
#   NON-PURCHASE "success" paths found (both bypass verification
#   entirely, both a giveaway, not a sale):
#     - chat_pack_service.py::add_reward_question() (watch-2-ads reward):
#       when the user has no active pack, creates a NEW row directly at
#       status="success", amount=0, razorpay_order_id=
#       razorpay_payment_id="REWARD_AD". (When the user DOES have an
#       active pack, this instead increments that EXISTING row's
#       questions_total by 1 -- no new row, and that row's own
#       amount/razorpay_order_id are whatever they already were, so a
#       genuine buyer who also claims a reward is correctly unaffected --
#       Regression Matrix Case H.)
#     - routes/routes_chat.py::debug_add_or_reset_pack() action="add"
#       (admin-only support tool, gated by admin_required): creates a
#       row directly at status="success", razorpay_order_id=
#       razorpay_payment_id="ADMIN_ADD" -- amount=51, a POSITIVE amount,
#       which is exactly why `amount > 0` ALONE would not have been a
#       correct fix; the sentinel-marker exclusion is load-bearing.
#
# No other ChatPack.status="success" write site exists in this
# repository (verified via `git grep 'status.*=.*"success"'` /
# `status="success"` across modules/services + routes).
_NON_PURCHASE_CHATPACK_MARKERS = ("REWARD_AD", "ADMIN_ADD")


def _ask_now_buyer_expr():
    """Correlated EXISTS: a GENUINELY PAID, successfully verified
    ChatPack purchase for this users.id (U5A correction -- see the
    purchase-path audit comment above _NON_PURCHASE_CHATPACK_MARKERS).
    ChatPack.user_id is already users.id directly -- no bridge needed
    (Ask Now is users.id-scoped throughout this codebase).

    Predicate, in order:
      - status == "success" (unchanged from before this fix -- pending/
        failed rows never counted and still never do).
      - amount > 0 -- excludes the REWARD_AD giveaway (amount=0)
        directly; kept as an INDEPENDENT guard (not the only one) so a
        hypothetical future zero-amount non-purchase grant is excluded
        even if it reuses neither known sentinel string.
      - razorpay_order_id NOT ONE OF the two known non-purchase sentinel
        markers -- this is what correctly excludes ADMIN_ADD (amount=51,
        which amount > 0 alone would NOT catch). A NULL
        razorpay_order_id (e.g. a pre-existing test fixture built before
        this field mattered) is explicitly NOT excluded here -- this
        predicate only excludes rows with POSITIVE evidence of being a
        known non-purchase pattern; it never guesses "no order id ->
        not a real purchase" beyond that, per this task's own "use
        durable business evidence" instruction and to avoid a false
        negative regression on any pre-existing genuine-purchase
        fixture that never set this optional field."""
    return (
        db.session.query(ChatPack.id)
        .filter(
            ChatPack.user_id == User.id,
            ChatPack.status == "success",
            ChatPack.amount > 0,
            or_(
                ChatPack.razorpay_order_id.is_(None),
                ChatPack.razorpay_order_id.notin_(_NON_PURCHASE_CHATPACK_MARKERS),
            ),
        )
        .correlate(User)
        .exists()
    )


def _ask_now_concern_expr(categories: list):
    """U5A -- Correlated EXISTS: at least one classified Ask Now question
    (modules/models_ask_now_intent_history.py::AskNowIntentHistory) whose
    concern_category is one of the requested `categories`. Read-only
    against Ask Now's own existing, already-written history table --
    no new storage. AskNowIntentHistory.user_id is already users.id
    directly (see that model's own docstring) -- no bridge needed, and
    it carries no FK constraint, so an orphaned user_id (pointing to no
    live users.id row -- theoretically possible, never expected in
    practice) simply never matches here, because this EXISTS is always
    correlated against a real `User` row to begin with -- it can never
    fabricate a phantom Admin user from an orphaned history row.

    OR-within: multiple `categories` are combined via SQL IN (...) --
    matching this file's existing convention for every other multi-value
    filter (moon_sign/lagna/yog/dosh/mahadasha/...). AND-across: the
    caller (list_users()) combines this with every other filter via a
    plain .filter() call, exactly like every other dimension here."""
    return (
        db.session.query(AskNowIntentHistory.id)
        .filter(
            AskNowIntentHistory.user_id == User.id,
            AskNowIntentHistory.concern_category.in_(categories),
        )
        .correlate(User)
        .exists()
    )


def _app_user_id_bridge_expr():
    """Correlated scalar subquery: the app_users.id (profile_id) reached
    from this users row via the firebase_uid bridge. NULL whenever
    users.firebase_uid is NULL or no AppUser shares it -- never guessed."""
    return (
        db.session.query(AppUser.id)
        .filter(AppUser.firebase_uid == User.firebase_uid)
        .correlate(User)
        .scalar_subquery()
    )


def _entitlement_plan_expr():
    """Correlated scalar subquery: CurrentEntitlement.plan reached
    through the firebase_uid bridge. NULL whenever the bridge can't be
    completed OR the profile has never purchased a plan (CurrentEntitlement's
    own documented meaning of plan IS NULL)."""
    return (
        db.session.query(CurrentEntitlement.plan)
        .filter(CurrentEntitlement.profile_id == _app_user_id_bridge_expr())
        .correlate(User)
        .scalar_subquery()
    )


def _entitlement_status_expr():
    """Correlated scalar subquery: CurrentEntitlement.status through the
    same bridge. NULL whenever no entitlement row/bridge exists."""
    return (
        db.session.query(CurrentEntitlement.status)
        .filter(CurrentEntitlement.profile_id == _app_user_id_bridge_expr())
        .correlate(User)
        .scalar_subquery()
    )


def _last_active_expr():
    """Correlated scalar subquery: MAX(activity_events.occurred_at)
    matched directly by users.firebase_uid (no bridge -- firebase_uid is
    a real column on `users` itself, and activity_events.firebase_uid is
    backed by a (firebase_uid, occurred_at) composite index for exactly
    this lookup shape), restricted to event_name == ACTIVE_EVENT_NAME
    ("session_start") -- U2.1's "opened the app" redefinition. NULL
    whenever firebase_uid is NULL (the WHERE clause can then never match
    anything) or whenever no session_start has ever been recorded for a
    known firebase_uid (including a user who is active via OTHER events
    only -- that is the intended, locked behavior, not an oversight)."""
    return (
        db.session.query(func.max(ActivityEvent.occurred_at))
        .filter(
            ActivityEvent.firebase_uid == User.firebase_uid,
            ActivityEvent.event_name == ACTIVE_EVENT_NAME,
        )
        .correlate(User)
        .scalar_subquery()
    )


def _status_expr(last_active_expr):
    """active / inactive / unknown, per the locked rule -- "unknown"
    covers BOTH "no firebase_uid at all" and "firebase_uid known but zero
    identified activity ever recorded". Never collapses either case into
    "inactive"."""
    cutoff = datetime.utcnow() - timedelta(days=LAST_ACTIVE_WINDOW_DAYS)
    return case(
        (User.firebase_uid.is_(None), literal("unknown")),
        (last_active_expr.is_(None), literal("unknown")),
        (last_active_expr >= cutoff, literal("active")),
        else_=literal("inactive"),
    )


def _bridged_app_user_dob_expr():
    """Correlated scalar subquery: app_users.dob reached via the SAME
    firebase_uid bridge _app_user_id_bridge_expr()/_entitlement_plan_expr()
    already use -- never users.id == app_users.id, never email/phone
    matching. NULL whenever users.firebase_uid is NULL or no AppUser
    shares it. app_users.firebase_uid is a PARTIAL UNIQUE index (WHERE
    firebase_uid IS NOT NULL -- modules/models_user.py), so this can
    never resolve to more than one row."""
    return (
        db.session.query(AppUser.dob)
        .filter(AppUser.firebase_uid == User.firebase_uid)
        .correlate(User)
        .scalar_subquery()
    )


def _moon_sign_expr():
    """Correlated scalar subquery: app_users.moon_sign via the SAME
    firebase_uid bridge as _bridged_app_user_dob_expr(). Reused as
    stored -- never recalculated (see BIRTH ASTROLOGY docstring above).
    NULL whenever the bridge can't be completed or the field was never
    populated for the linked profile."""
    return (
        db.session.query(AppUser.moon_sign)
        .filter(AppUser.firebase_uid == User.firebase_uid)
        .correlate(User)
        .scalar_subquery()
    )


def _lagna_expr():
    """Correlated scalar subquery: app_users.lagna via the same bridge."""
    return (
        db.session.query(AppUser.lagna)
        .filter(AppUser.firebase_uid == User.firebase_uid)
        .correlate(User)
        .scalar_subquery()
    )


def _nakshatra_expr():
    """Correlated scalar subquery: app_users.nakshatra via the same bridge."""
    return (
        db.session.query(AppUser.nakshatra)
        .filter(AppUser.firebase_uid == User.firebase_uid)
        .correlate(User)
        .scalar_subquery()
    )


def _nakshatra_pada_expr():
    """Correlated scalar subquery: app_users.nakshatra_pada via the same bridge."""
    return (
        db.session.query(AppUser.nakshatra_pada)
        .filter(AppUser.firebase_uid == User.firebase_uid)
        .correlate(User)
        .scalar_subquery()
    )


def _static_yog_expr():
    """Correlated scalar subquery: app_users.static_yog (JSONB) via the
    same bridge. NULL = not calculated; {} = calculated, none active;
    a sparse object = calculated, only the active Yog as keys."""
    return (
        db.session.query(AppUser.static_yog)
        .filter(AppUser.firebase_uid == User.firebase_uid)
        .correlate(User)
        .scalar_subquery()
    )


def _static_dosh_expr():
    """Correlated scalar subquery: app_users.static_dosh (JSONB) via the
    same bridge. Same NULL/{}/sparse contract as static_yog above."""
    return (
        db.session.query(AppUser.static_dosh)
        .filter(AppUser.firebase_uid == User.firebase_uid)
        .correlate(User)
        .scalar_subquery()
    )


def _static_astrology_calculated_at_expr():
    """Correlated scalar subquery: app_users.static_astrology_calculated_at
    via the same bridge -- the single authoritative "was this profile's
    static astrology ever calculated" signal (NULL = never)."""
    return (
        db.session.query(AppUser.static_astrology_calculated_at)
        .filter(AppUser.firebase_uid == User.firebase_uid)
        .correlate(User)
        .scalar_subquery()
    )


def _static_astrology_version_expr():
    """Correlated scalar subquery: app_users.static_astrology_version
    via the same bridge -- detail-only, never filtered on."""
    return (
        db.session.query(AppUser.static_astrology_version)
        .filter(AppUser.firebase_uid == User.firebase_uid)
        .correlate(User)
        .scalar_subquery()
    )


def _current_dasha_row_id_expr():
    """U4A.3 -- the primary key of the ONE UserDashaTimeline row that is
    CURRENT for this user, under the FROZEN half-open interval rule
    verified in U4A.0/U4A.1/U4A.2:

        start_date <= CURRENT_DATE AND end_date > CURRENT_DATE

    (never `>= end_date` -- on an exact transition date the INCOMING
    period is current, never the outgoing one). Reached via the SAME
    firebase_uid -> app_users.id bridge every other bridged expression
    in this file already uses -- never a second identity resolution.
    NULL whenever the bridge can't be completed, the linked profile has
    no timeline at all, or no row's window currently covers today (a
    genuinely uncalculated/uncovered case, never guessed).

    `ORDER BY start_date DESC LIMIT 1` is a defensive tie-breaker for a
    theoretically-corrupt timeline (U4A.2's own validator is what
    actually guards against that in the backfill/write paths) -- for a
    healthy timeline the UNIQUE(user_id, mahadasha, antardasha)
    constraint plus the proven half-open, non-overlapping generation
    means at most one row can ever match this predicate anyway.

    This is the ONLY place the "which row is current" decision is made.
    _current_dasha_field_expr() below reads every other Dasha field by
    THIS SAME row's primary key -- never by re-running the date
    predicate a second time -- so Mahadasha/Antardasha/start/end can
    never be pieced together from two different rows (a primary-key
    equality match can only ever resolve to the one row that id
    belongs to, or none)."""
    return (
        db.session.query(UserDashaTimeline.id)
        .filter(
            UserDashaTimeline.user_id == _app_user_id_bridge_expr(),
            UserDashaTimeline.start_date <= func.current_date(),
            UserDashaTimeline.end_date > func.current_date(),
        )
        .order_by(UserDashaTimeline.start_date.desc())
        .limit(1)
        .correlate(User)
        .scalar_subquery()
    )


def _current_dasha_field_expr(current_row_id_expr, column):
    """One field of the CURRENT Dasha row, resolved by the exact same
    row id _current_dasha_row_id_expr() already determined -- see that
    function's own docstring for the same-row guarantee this provides."""
    return (
        db.session.query(column)
        .filter(UserDashaTimeline.id == current_row_id_expr)
        .correlate(User)
        .scalar_subquery()
    )


def _sade_sati_exprs(moon_sign_expr, resolved_saturn_sign: str):
    """U4B.2 -- builds the SQL CASE expressions for Sade Sati active/
    phase, for THIS request's already-resolved current Saturn sign.

    NOT a second astrology implementation: this calls the ONE shared
    classify_sade_sati() once per canonical Moon sign (12 pure-Python
    calls, zero ephemeris, zero DB) to learn exactly which Moon signs
    are currently active (and in which phase) for this specific Saturn
    sign, then compiles that result into a SQL CASE -- the CASE is a
    literal SQL rendering of the classifier's own output for this one
    Saturn sign, never an independently-derived rule. A future change
    to classify_sade_sati()'s own math is picked up automatically here,
    with no parallel logic to keep in sync (see
    test_admin_sade_sati.py's 144-combination parity proof).

    NULL semantics preserved exactly: moon_sign_expr NULL or not one of
    the 12 canonical signs -> active=NULL, phase=NULL (NOT_CALCULATED,
    never False) -- matching classify_sade_sati()'s own contract."""
    active_signs_by_phase = {PHASE_FIRST: [], PHASE_SECOND: [], PHASE_THIRD: []}
    for candidate_sign in CANONICAL_SIGNS:
        result = classify_sade_sati(candidate_sign, resolved_saturn_sign)
        if result["state"] == STATE_ACTIVE:
            active_signs_by_phase[result["phase"]].append(candidate_sign)

    # By construction of the classifier's own math, exactly one Moon
    # sign maps to each of the 3 phases for any valid Saturn sign --
    # never zero, never more than one per phase (proven for all 144
    # Moon x Saturn combinations in test_admin_sade_sati.py).
    phase_expr = case(
        *[(moon_sign_expr.in_(signs), literal(phase)) for phase, signs in active_signs_by_phase.items()],
        else_=literal(None),
    )

    all_active_signs = [s for signs in active_signs_by_phase.values() for s in signs]
    active_expr = case(
        (moon_sign_expr.in_(all_active_signs), literal(True)),
        (moon_sign_expr.in_(CANONICAL_SIGNS), literal(False)),
        else_=literal(None),
    )
    return active_expr, phase_expr


def _lagna_signs_for_house(planet_sign: str, houses: list) -> list:
    """U4C.3 -- the SQL-side inverse of the canonical house formula.

    NOT a second Jyotish formula: this calls the ONE shared
    calculate_house() once per canonical Lagna sign (12 pure-Python
    calls, zero ephemeris, zero DB) against THIS request's already-
    resolved current `planet_sign`, and returns exactly which Lagna
    signs would put that planet in one of the requested `houses` --
    literally the SAME technique _sade_sati_exprs() above already
    established for classify_sade_sati(). The caller then filters the
    bridged AppUser.lagna column with a plain SQL `IN (...)` against
    this list -- never a per-row calculation, never a stored house.

    Because calculate_house() is a bijection between Lagna sign and
    house for a FIXED planet_sign (each of the 12 candidate Lagna signs
    maps to a distinct house 1-12), this returns exactly one Lagna sign
    per requested house -- never zero, never more than one per house
    (proven exhaustively in test_admin_transit.py's own 144-combination
    parity test)."""
    return [
        candidate for candidate in CANONICAL_SIGNS
        if calculate_house(candidate, planet_sign) in houses
    ]


def _age_expr():
    """
    U2.1 -- Age derived from users.dob first, falling back to the
    bridged app_users.dob only when users.dob is missing/malformed.
    Both sources are independently validated against the exact
    YYYY-MM-DD shape before being trusted -- neither is ever guessed or
    repaired; a genuinely DOB-less/malformed-on-both-sides user still
    yields SQL NULL (never fabricated).

    Uses to_date(), not a hard `::date` CAST, specifically because
    Postgres's to_date() is documented as format-driven/tolerant rather
    than raising on an out-of-range-but-digit-shaped value (e.g. day 31
    in a 30-day month) the way a plain cast would -- the regex guard
    already excludes non-date-shaped garbage (empty string, free text)
    from ever reaching to_date() at all. A residual class of "wrong but
    digit-shaped" DOB values may still yield a slightly-off age rather
    than a null one; this is an accepted, documented trade-off, not a
    silent hazard.
    """
    bridged_dob = _bridged_app_user_dob_expr()
    users_dob_valid = and_(User.dob.isnot(None), User.dob.op("~")(_DOB_SHAPE_RE))
    bridged_dob_valid = and_(bridged_dob.isnot(None), bridged_dob.op("~")(_DOB_SHAPE_RE))
    resolved_dob = case(
        (users_dob_valid, User.dob),
        (bridged_dob_valid, bridged_dob),
        else_=None,
    )
    dob_date = func.to_date(resolved_dob, "YYYY-MM-DD")
    return case(
        (or_(users_dob_valid, bridged_dob_valid), func.extract("year", func.age(func.current_date(), dob_date))),
        else_=None,
    )


def _jsonb_has_any_key(jsonb_expr, keys):
    """Postgres JSONB "has any of these keys" (`?|`), applied directly
    to a correlated scalar-subquery expression -- SQLAlchemy's own
    `.has_any()` JSONB comparator is not reachable through a
    ScalarSelect wrapper (verified directly: raises AttributeError), so
    the raw operator is used instead via `.op()`, the same technique
    U2.1's `_age_expr()` already uses for `~` on a scalar subquery.
    `NULL ?| array[...]` and `'{}'::jsonb ?| array[...]` both evaluate
    to NULL/false in Postgres -- an uncalculated or empty document
    never matches, with no special-casing needed here."""
    return jsonb_expr.op("?|")(cast(pg_array(keys), ARRAY(TEXT)))


def _customer_type_expr(ask_now_buyer_expr, plan_expr):
    return case(
        (or_(ask_now_buyer_expr, plan_expr.isnot(None)), literal("paying")),
        else_=literal("free"),
    )


def _base_columns(resolved_saturn_sign: str):
    """The exact set of expressions both list_users() and
    get_user_detail() select -- kept in one place so the two can never
    drift in which rule they apply for a given field.

    `resolved_saturn_sign` is the ONE current-Saturn sign
    resolve_current_saturn_sign() already produced for this request
    (U4B.2) -- this function never resolves Saturn itself, so calling
    it more than once per request never triggers a second resolution."""
    last_active_expr = _last_active_expr()
    ask_now_buyer_expr = _ask_now_buyer_expr()
    plan_expr = _entitlement_plan_expr()
    entitlement_status_expr = _entitlement_status_expr()
    active_sub_expr = entitlement_status_expr.in_(ACTIVE_SUBSCRIPTION_STATUSES)
    status_expr = _status_expr(last_active_expr)
    customer_type_expr = _customer_type_expr(ask_now_buyer_expr, plan_expr)
    age_expr = _age_expr()
    moon_sign_expr = _moon_sign_expr()
    lagna_expr = _lagna_expr()
    nakshatra_expr = _nakshatra_expr()
    nakshatra_pada_expr = _nakshatra_pada_expr()
    static_yog_expr = _static_yog_expr()
    static_dosh_expr = _static_dosh_expr()
    static_astrology_calculated_at_expr = _static_astrology_calculated_at_expr()
    static_astrology_version_expr = _static_astrology_version_expr()
    current_dasha_row_id_expr = _current_dasha_row_id_expr()
    current_mahadasha_expr = _current_dasha_field_expr(current_dasha_row_id_expr, UserDashaTimeline.mahadasha)
    current_antardasha_expr = _current_dasha_field_expr(current_dasha_row_id_expr, UserDashaTimeline.antardasha)
    current_dasha_start_expr = _current_dasha_field_expr(current_dasha_row_id_expr, UserDashaTimeline.start_date)
    current_dasha_end_expr = _current_dasha_field_expr(current_dasha_row_id_expr, UserDashaTimeline.end_date)
    sade_sati_active_expr, sade_sati_phase_expr = _sade_sati_exprs(moon_sign_expr, resolved_saturn_sign)

    columns = (
        User.id,
        User.name,
        User.email,
        User.phone,
        age_expr.label("age"),
        status_expr.label("status"),
        customer_type_expr.label("customer_type"),
        active_sub_expr.label("active_subscription"),
        ask_now_buyer_expr.label("ask_now_buyer"),
        User.created_at.label("signup_date"),
        last_active_expr.label("last_active_at"),
        moon_sign_expr.label("moon_sign"),
        lagna_expr.label("lagna"),
        nakshatra_expr.label("nakshatra"),
        nakshatra_pada_expr.label("nakshatra_pada"),
        static_yog_expr.label("static_yog"),
        static_dosh_expr.label("static_dosh"),
        static_astrology_calculated_at_expr.label("static_astrology_calculated_at"),
        static_astrology_version_expr.label("static_astrology_version"),
        current_mahadasha_expr.label("current_mahadasha"),
        current_antardasha_expr.label("current_antardasha"),
        current_dasha_start_expr.label("current_dasha_start_date"),
        current_dasha_end_expr.label("current_dasha_end_date"),
        sade_sati_active_expr.label("sade_sati_active"),
        sade_sati_phase_expr.label("sade_sati_phase"),
    )
    filter_exprs = {
        "age": age_expr,
        "status": status_expr,
        "customer_type": customer_type_expr,
        "active_subscription": active_sub_expr,
        "ask_now_buyer": ask_now_buyer_expr,
        "moon_sign": moon_sign_expr,
        "lagna": lagna_expr,
        "nakshatra": nakshatra_expr,
        "nakshatra_pada": nakshatra_pada_expr,
        "static_yog": static_yog_expr,
        "static_dosh": static_dosh_expr,
        "current_mahadasha": current_mahadasha_expr,
        "current_antardasha": current_antardasha_expr,
        "sade_sati_active": sade_sati_active_expr,
        "sade_sati_phase": sade_sati_phase_expr,
    }
    return columns, filter_exprs


def _serialize_row(row) -> dict:
    """The single, richest serialization both list_users() and
    get_user_detail() build from -- each caller then picks its own
    appropriate view (see _list_row_view() below for the compact list
    shape). static_yog/static_dosh here are the RAW stored JSONB
    (None/{}/sparse-dict, per the frozen calculated/uncalculated
    contract) -- active_yog/active_dosh are derived from them, in
    Python, purely for the already-fetched, already-paginated current
    page's presentation (never a second query, never how filtering is
    decided -- filtering happens in SQL, see list_users())."""
    static_yog = row.static_yog
    static_dosh = row.static_dosh
    return {
        "id": row.id,
        "name": row.name,
        "email": row.email,
        "phone": row.phone,
        "age": int(row.age) if row.age is not None else None,
        "status": row.status,
        "customer_type": row.customer_type,
        "active_subscription": bool(row.active_subscription),
        "ask_now_buyer": bool(row.ask_now_buyer),
        "signup_date": row.signup_date.isoformat() if row.signup_date else None,
        "last_active_at": row.last_active_at.isoformat() if row.last_active_at else None,
        "moon_sign": row.moon_sign,
        "lagna": row.lagna,
        "nakshatra": row.nakshatra,
        "nakshatra_pada": row.nakshatra_pada,
        # NULL (uncalculated) stays None -- never fabricated into [].
        # {} (calculated, none active/present) stays [] -- a real,
        # meaningful empty list, distinct from None.
        "active_yog": list(static_yog.keys()) if static_yog is not None else None,
        "active_dosh": list(static_dosh.keys()) if static_dosh is not None else None,
        "static_yog": static_yog,
        "static_dosh": static_dosh,
        "static_astrology_calculated_at": (
            row.static_astrology_calculated_at.isoformat() if row.static_astrology_calculated_at else None
        ),
        "static_astrology_version": row.static_astrology_version,
        # U4A.3 -- read-only, from the persisted UserDashaTimeline ONLY
        # (never calculate_vimshottari_dasha()/get_moon_longitude_lahiri(),
        # never a fresh computation). null whenever the bridge fails, no
        # timeline exists, or no row currently covers today -- never
        # fabricated into a placeholder string. current_mahadasha and
        # current_antardasha are guaranteed to originate from the SAME
        # timeline row (see _current_dasha_row_id_expr()'s own docstring).
        "current_mahadasha": row.current_mahadasha,
        "current_antardasha": row.current_antardasha,
        # Detail-only raw dates -- never in the compact list view (see
        # _LIST_ONLY_EXCLUDED_FIELDS below). get_user_detail() packs
        # these, together with the two fields above, into one
        # birth_astrology.current_dasha object.
        "current_dasha_start_date": (
            row.current_dasha_start_date.isoformat() if row.current_dasha_start_date else None
        ),
        "current_dasha_end_date": (
            row.current_dasha_end_date.isoformat() if row.current_dasha_end_date else None
        ),
        # U4B.2 -- read-only, derived from persisted AppUser.moon_sign +
        # the ONE current Saturn sign already resolved for this request
        # (never a per-user ephemeris call). null/null means natal Moon
        # sign is unavailable (NOT_CALCULATED) -- never fabricated as
        # false, never labeled "Unknown".
        "sade_sati_active": row.sade_sati_active,
        "sade_sati_phase": row.sade_sati_phase,
    }


# Detail-only fields _serialize_row() computes but the compact LIST
# response must never include (raw JSONB / version -- U3B.3's own
# explicit compactness rule: list returns machine-key arrays only).
# U4A.3 -- current_dasha_start_date/current_dasha_end_date are ALSO
# detail-only: the list response gets the flat current_mahadasha/
# current_antardasha fields per this task's own contract, but never the
# raw start/end dates -- those are only ever surfaced nested inside
# get_user_detail()'s birth_astrology.current_dasha object.
_LIST_ONLY_EXCLUDED_FIELDS = (
    "static_yog", "static_dosh", "static_astrology_version",
    "current_dasha_start_date", "current_dasha_end_date",
)


def _list_row_view(serialized: dict) -> dict:
    return {k: v for k, v in serialized.items() if k not in _LIST_ONLY_EXCLUDED_FIELDS}


# ---------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------

def get_users_summary() -> dict:
    """The 4 top-level summary counts -- independent of any list filter/
    pagination. Each is one COUNT(*) query against the same expression
    builders list_users()/get_user_detail() use, so the summary numbers
    and the filtered list can never define "active"/"paying" differently."""
    last_active_expr = _last_active_expr()
    status_expr = _status_expr(last_active_expr)
    ask_now_buyer_expr = _ask_now_buyer_expr()
    plan_expr = _entitlement_plan_expr()
    entitlement_status_expr = _entitlement_status_expr()

    total_users = db.session.query(func.count(User.id)).scalar() or 0

    active_users = (
        db.session.query(func.count(User.id))
        .filter(status_expr == "active")
        .scalar() or 0
    )

    paying_users = (
        db.session.query(func.count(User.id))
        .filter(or_(ask_now_buyer_expr, plan_expr.isnot(None)))
        .scalar() or 0
    )

    active_subscriptions = (
        db.session.query(func.count(User.id))
        .filter(entitlement_status_expr.in_(ACTIVE_SUBSCRIPTION_STATUSES))
        .scalar() or 0
    )

    return {
        "total_users": total_users,
        "active_users": active_users,
        "paying_users": paying_users,
        "active_subscriptions": active_subscriptions,
    }


def _apply_admin_users_filters(
    query,
    f: dict,
    *,
    id_in: list = None,
    search: str = None,
    age_min: int = None,
    age_max: int = None,
    status: str = None,
    signup_from: str = None,
    signup_to: str = None,
    customer_type: str = None,
    ask_now_buyer: bool = None,
    active_subscription: bool = None,
    moon_sign: list = None,
    lagna: list = None,
    nakshatra: list = None,
    nakshatra_pada: list = None,
    yog: list = None,
    dosh: list = None,
    mahadasha: list = None,
    antardasha: list = None,
    sade_sati_active: bool = None,
    sade_sati_phase: list = None,
    jupiter_house: list = None,
    saturn_house: list = None,
    rahu_house: list = None,
    ketu_house: list = None,
    ask_now_concern: list = None,
    language: list = None,
):
    """U6A -- THE ONE shared WHERE-clause builder behind BOTH list_users()
    (Admin Users list/table) and resolve_user_ids() (Saved Audience
    resolution) -- extracted verbatim from list_users()'s own filter
    block, byte-for-byte identical logic, so the two can never drift
    into two different definitions of "who matches this criteria."
    Every filter semantic documented on list_users()'s own docstring
    (OR-within/AND-across, lazy transit-snapshot resolution, exactly-
    once Sade Sati/transit resolution, no per-row ephemeris) applies
    here unchanged -- this function IS that logic, not a re-description
    of it.

    `query` must already be a `db.session.query(...)` built against the
    `User` entity (any column/entity list -- the full richly-labeled
    columns list_users() selects, or just `User.id` for
    resolve_user_ids()); `f` must be the `filter_exprs` dict
    `_base_columns()` already returned for THIS SAME request's resolved
    Saturn sign. Returns the filtered (not yet ordered/paginated) query.

    Raises TransitUnavailableError if a transit-house filter is
    requested and resolve_current_transit_snapshot() fails -- same
    contract as list_users() already had before this extraction.

    `id_in` (Saved Audience V2, keyword-only, internal use only -- NEVER
    part of the DYNAMIC criteria JSON schema in modules/services/
    saved_audience_criteria.py's _FILTER_VALIDATORS, never accepted from
    untrusted input) restricts to an explicit set of users.id values.
    Used exclusively by saved_audience_service.py to render a FIXED
    audience's membership through this SAME rich row-shape/pagination
    logic every DYNAMIC audience and the live Admin Users list already
    use -- never a second, differently-shaped member listing. An empty
    list correctly yields zero rows (SQLAlchemy's IN (), not "no
    filter")."""
    if id_in is not None:
        query = query.filter(User.id.in_(id_in))

    if language is not None:
        if not isinstance(language, list) or not language or any(v not in ("en", "hi") for v in language):
            raise ValueError("invalid_language")
        # UID correlation, guarded against ambiguous profiles; no Python membership filtering.
        from sqlalchemy import func
        from modules.models_user import AppUser
        profile_count = (db.session.query(func.count(AppUser.id))
                         .filter(AppUser.firebase_uid == User.firebase_uid)
                         .correlate(User).scalar_subquery())
        normalized = func.lower(func.regexp_replace(AppUser.lang, r"^\s+|\s+$", "", "g"))
        matching = (db.session.query(AppUser.id)
                    .filter(AppUser.firebase_uid == User.firebase_uid, normalized.in_(language))
                    .correlate(User).exists())
        query = query.filter(User.firebase_uid.isnot(None),
                             func.length(func.regexp_replace(User.firebase_uid, r"\s", "", "g")) > 0,
                             profile_count == 1, matching)

    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(User.name.ilike(term), User.email.ilike(term), User.phone.ilike(term))
        )
    if age_min is not None:
        query = query.filter(f["age"] >= age_min)
    if age_max is not None:
        query = query.filter(f["age"] <= age_max)
    if status:
        query = query.filter(f["status"] == status)
    if signup_from:
        query = query.filter(User.created_at >= signup_from)
    if signup_to:
        query = query.filter(User.created_at <= signup_to)
    if customer_type:
        query = query.filter(f["customer_type"] == customer_type)
    if ask_now_buyer is True:
        query = query.filter(f["ask_now_buyer"])
    elif ask_now_buyer is False:
        query = query.filter(~f["ask_now_buyer"])
    if active_subscription is True:
        query = query.filter(f["active_subscription"])
    elif active_subscription is False:
        query = query.filter(~f["active_subscription"])
    if moon_sign:
        query = query.filter(f["moon_sign"].in_(moon_sign))
    if lagna:
        query = query.filter(f["lagna"].in_(lagna))
    if nakshatra:
        query = query.filter(f["nakshatra"].in_(nakshatra))
    if nakshatra_pada:
        query = query.filter(f["nakshatra_pada"].in_(nakshatra_pada))
    if yog:
        query = query.filter(_jsonb_has_any_key(f["static_yog"], yog))
    if dosh:
        query = query.filter(_jsonb_has_any_key(f["static_dosh"], dosh))
    if mahadasha:
        query = query.filter(f["current_mahadasha"].in_(mahadasha))
    if antardasha:
        query = query.filter(f["current_antardasha"].in_(antardasha))
    if sade_sati_active is True:
        query = query.filter(f["sade_sati_active"].is_(True))
    elif sade_sati_active is False:
        query = query.filter(f["sade_sati_active"].is_(False))
    if sade_sati_phase:
        query = query.filter(f["sade_sati_phase"].in_(sade_sati_phase))

    # U4C.3 -- current-transit-house filters. Resolved AT MOST ONCE,
    # lazily, only if at least one of the 4 params was requested (see
    # list_users()'s own docstring). Never a stored house, never a
    # per-row ephemeris call -- _lagna_signs_for_house() does pure
    # Python inverse arithmetic against the ONE already-resolved
    # transit_snapshot, and the result is applied as a plain SQL
    # `IN (...)` against the SAME bridged lagna_expr the existing
    # `lagna` filter already uses.
    if jupiter_house or saturn_house or rahu_house or ketu_house:
        try:
            transit_snapshot = resolve_current_transit_snapshot()
        except Exception as exc:
            raise TransitUnavailableError(str(exc)) from exc

        if jupiter_house:
            query = query.filter(f["lagna"].in_(
                _lagna_signs_for_house(transit_snapshot.rashi("Jupiter"), jupiter_house)
            ))
        if saturn_house:
            query = query.filter(f["lagna"].in_(
                _lagna_signs_for_house(transit_snapshot.rashi("Saturn"), saturn_house)
            ))
        if rahu_house:
            query = query.filter(f["lagna"].in_(
                _lagna_signs_for_house(transit_snapshot.rashi("Rahu"), rahu_house)
            ))
        if ketu_house:
            query = query.filter(f["lagna"].in_(
                _lagna_signs_for_house(transit_snapshot.rashi("Ketu"), ketu_house)
            ))

    # U5A -- Ask Now Concern filter. Plain correlated EXISTS against
    # ask_now_intent_history, no snapshot/resolver involved (unlike the
    # transit-house filters above) -- SQL-side, folded into this same
    # query, no extra round-trip.
    if ask_now_concern:
        query = query.filter(_ask_now_concern_expr(ask_now_concern))

    return query


def list_users(
    *,
    id_in: list = None,
    search: str = None,
    age_min: int = None,
    age_max: int = None,
    status: str = None,
    signup_from: str = None,
    signup_to: str = None,
    customer_type: str = None,
    ask_now_buyer: bool = None,
    active_subscription: bool = None,
    moon_sign: list = None,
    lagna: list = None,
    nakshatra: list = None,
    nakshatra_pada: list = None,
    yog: list = None,
    dosh: list = None,
    mahadasha: list = None,
    antardasha: list = None,
    sade_sati_active: bool = None,
    sade_sati_phase: list = None,
    jupiter_house: list = None,
    saturn_house: list = None,
    rahu_house: list = None,
    ketu_house: list = None,
    ask_now_concern: list = None,
    language: list = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """Search + U2 basic filters + U3A Birth Astrology filters + U3B.3
    Pada/Yog/Dosh filters + U4A.3 current-Dasha filters + pagination, in
    ONE SQL query for the page plus ONE SQL query for the total count --
    never a per-row query, and never a call into the astrology engine or
    any individual Yog/Dosh evaluator (moon_sign/lagna/nakshatra/
    nakshatra_pada/mahadasha/antardasha are plain stored-value equality/
    membership checks; yog/dosh are Postgres JSONB key-presence checks
    against the bridged, already-stored static_yog/static_dosh columns;
    mahadasha/antardasha are plain equality checks against the
    persisted, already-computed UserDashaTimeline row that is CURRENT
    for a profile -- never get_moon_longitude_lahiri()/
    calculate_vimshottari_dasha(), never a write).

    moon_sign/lagna/nakshatra/nakshatra_pada/yog/dosh/mahadasha/
    antardasha are each an optional LIST of canonical values --
    multiple values within one dimension are OR'd together (SQL
    IN (...) for scalar columns, JSONB `?|` "has any key" for yog/dosh);
    every dimension (and every other filter here) combines with AND,
    exactly like every other independent filter in this function
    already does -- so `mahadasha=Saturn,Mercury&antardasha=Venus,Moon`
    means (Maha IN (Saturn,Mercury)) AND (Antar IN (Venus,Moon)). Both
    conditions are evaluated against current_mahadasha_expr/
    current_antardasha_expr, which are BOTH derived from the exact same
    _current_dasha_row_id_expr() -- so a profile can only match this
    combined filter if ONE single current timeline row satisfies both,
    never a Mahadasha from one row paired with an Antardasha from
    another. An uncalculated (NULL) or calculated-but-empty ({})
    static_yog/static_dosh document never matches a yog/dosh filter,
    and a profile with no valid current Dasha row never matches a
    mahadasha/antardasha filter -- Postgres's own NULL semantics already
    guarantee both with no special-casing.

    U4B.2 -- sade_sati_active (bool) / sade_sati_phase (list of the 3
    canonical phase strings, OR'd together) work the same way, derived
    from persisted AppUser.moon_sign + the ONE current Saturn sign
    resolved below (never a per-user ephemeris call, never a second
    astrology rule -- see _sade_sati_exprs()). resolve_current_saturn_sign()
    is called EXACTLY ONCE per call to this function -- never once per
    row, never once per filter, never once again for the count query
    (the count and the row query both reuse the SAME already-built
    `query` object, so the same resolved Saturn sign is embedded in
    both). A resolution failure raises SadeSatiUnavailableError before
    any query is built -- this function never silently classifies every
    user as inactive or fabricates a null in that case.

    U4C.3 -- jupiter_house/saturn_house/rahu_house/ketu_house (each an
    optional LIST of canonical house integers 1-12, OR'd together
    within one planet's dimension, AND'd across the 4 planets and every
    other filter here -- same convention as every other multi-value
    filter in this function) are current-TRANSIT-house filters, derived
    from AppUser.lagna + the ONE current transit snapshot resolved
    below, via the canonical calculate_house() formula -- never a
    stored house, never a per-row ephemeris call (see
    _lagna_signs_for_house()'s own docstring). This is DELIBERATELY
    LAZY, unlike Saturn's resolution above: resolve_current_transit_
    snapshot() is called AT MOST ONCE, and ONLY when at least one of
    these 4 params is actually provided -- the overwhelming majority of
    Admin list requests use none of them, and this function must not
    pay for a transit resolution they never asked for. When more than
    one of the 4 IS provided, all 4 house lookups reuse the SAME single
    resolved snapshot -- never triggering a second resolution. A
    resolution failure raises TransitUnavailableError before any
    further filtering is applied.

    NOTE (documented, not fixed -- see services/current_transit_
    resolver.py's own module docstring): this transit snapshot's
    current-Saturn value is resolved INDEPENDENTLY of
    resolve_current_saturn_sign() above (a different underlying engine,
    per U4B's own already-documented, deliberate source-selection
    decision) -- a request combining sade_sati_active/sade_sati_phase
    with saturn_house triggers two separate Saturn resolutions, proven
    to agree in practice (test_admin_transit.py), not merged into one.

    U5A -- ask_now_concern (optional LIST of category names, OR'd
    together, AND'd with every other filter here -- same convention as
    every other multi-value filter) is a read-only EXISTS against Ask
    Now's own existing, already-written ask_now_intent_history table
    (see _ask_now_concern_expr()) -- no new storage, no calculation, no
    per-row query (one correlated EXISTS clause folded into the SAME
    single page query and the SAME single count query every other
    filter already shares). Category values are validated by the ROUTE
    layer (routes_admin_users.py) against the DB-backed category
    master's CURRENTLY ACTIVE names (modules/services/
    asknow_category_service.py::get_active_category_names()) before
    this function is ever called -- this function itself does not
    re-validate, matching the existing division of labor for every
    other canonical-value filter in this file.

    U6A -- every filter semantic described above is now implemented in
    _apply_admin_users_filters(), a plain byte-for-byte extraction of
    what used to be inline in this function's own body -- resolve_user_ids()
    (Saved Audience resolution) calls that exact same function, so this
    is the ONE and only filter/astrology engine Admin Users and Saved
    Audiences both share. No behavior change from this extraction."""
    page = max(1, page or 1)
    page_size = max(1, min(page_size or 20, MAX_PAGE_SIZE))

    try:
        saturn_resolution = resolve_current_saturn_sign()
    except Exception as exc:
        raise SadeSatiUnavailableError(str(exc)) from exc

    columns, f = _base_columns(saturn_resolution.saturn_sign)
    query = db.session.query(*columns)

    # U6A -- WHERE-clause construction extracted into
    # _apply_admin_users_filters(), the ONE shared implementation
    # resolve_user_ids() (Saved Audience resolution) also calls -- this
    # is a pure extraction, byte-for-byte the same filter logic that was
    # inline here before, never a behavior change.
    query = _apply_admin_users_filters(
        query, f,
        id_in=id_in,
        search=search, age_min=age_min, age_max=age_max, status=status,
        signup_from=signup_from, signup_to=signup_to, customer_type=customer_type,
        ask_now_buyer=ask_now_buyer, active_subscription=active_subscription,
        moon_sign=moon_sign, lagna=lagna, nakshatra=nakshatra, nakshatra_pada=nakshatra_pada,
        yog=yog, dosh=dosh, mahadasha=mahadasha, antardasha=antardasha,
        sade_sati_active=sade_sati_active, sade_sati_phase=sade_sati_phase,
        jupiter_house=jupiter_house, saturn_house=saturn_house,
        rahu_house=rahu_house, ketu_house=ketu_house,
        ask_now_concern=ask_now_concern, language=language,
    )

    total_count = query.order_by(None).count()
    total_pages = max(1, math.ceil(total_count / page_size)) if total_count else 1

    rows = (
        query.order_by(User.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "users": [_list_row_view(_serialize_row(r)) for r in rows],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_count": total_count,
            "total_pages": total_pages,
        },
    }


def resolve_user_ids(
    *,
    search: str = None,
    age_min: int = None,
    age_max: int = None,
    status: str = None,
    signup_from: str = None,
    signup_to: str = None,
    customer_type: str = None,
    ask_now_buyer: bool = None,
    active_subscription: bool = None,
    moon_sign: list = None,
    lagna: list = None,
    nakshatra: list = None,
    nakshatra_pada: list = None,
    yog: list = None,
    dosh: list = None,
    mahadasha: list = None,
    antardasha: list = None,
    sade_sati_active: bool = None,
    sade_sati_phase: list = None,
    jupiter_house: list = None,
    saturn_house: list = None,
    rahu_house: list = None,
    ketu_house: list = None,
    ask_now_concern: list = None,
    language: list = None,
) -> list:
    """U6A -- Saved Audience resolution. Returns the full, UNPAGINATED
    list of canonical `users.id` values matching the given filters --
    the exact same filter set, in the exact same combined OR-within/
    AND-across semantics, that list_users()/GET /admin/api/users
    already implements, because this calls the SAME
    _apply_admin_users_filters() function list_users() itself calls --
    never a second astrology/filter engine, never a re-derived rule.

    Deliberately does NOT persist its return value -- Saved Audience
    membership is dynamic by design (U6.0's frozen architecture
    decision); this function is the resolver a future consumer (e.g. a
    Notification integration) calls fresh each time it needs the
    current membership, never a snapshot to write down.

    Selects ONLY User.id (never the full column/astrology payload
    list_users() selects) -- the right shape for a bulk-membership
    consumer, not a rendered Admin table page.

    Same invariants as list_users():
      - resolve_current_saturn_sign() is called EXACTLY ONCE per call to
        this function (never per row) -- a resolution failure raises
        SadeSatiUnavailableError before any query runs.
      - resolve_current_transit_snapshot() is called AT MOST ONCE, and
        ONLY if a transit-house filter was actually requested (the same
        lazy-resolution contract _apply_admin_users_filters() already
        has) -- a resolution failure raises TransitUnavailableError.
      - Zero per-user ephemeris calls -- explicitly NOT
        personalization_engine.get_users_for_transit()'s Python-loop-
        over-AppUser pattern (U6.0's own audit finding of what NOT to
        reuse here).

    Deterministic ordering: User.id ascending -- identical to
    list_users()'s own pagination ordering, so this function's first N
    ids are always the same N ids list_users(page=1, page_size=N) would
    return for the same criteria (proven in test_saved_audience.py's
    own filter-parity tests)."""
    try:
        saturn_resolution = resolve_current_saturn_sign()
    except Exception as exc:
        raise SadeSatiUnavailableError(str(exc)) from exc

    _, f = _base_columns(saturn_resolution.saturn_sign)
    query = db.session.query(User.id)
    query = _apply_admin_users_filters(
        query, f,
        search=search, age_min=age_min, age_max=age_max, status=status,
        signup_from=signup_from, signup_to=signup_to, customer_type=customer_type,
        ask_now_buyer=ask_now_buyer, active_subscription=active_subscription,
        moon_sign=moon_sign, lagna=lagna, nakshatra=nakshatra, nakshatra_pada=nakshatra_pada,
        yog=yog, dosh=dosh, mahadasha=mahadasha, antardasha=antardasha,
        sade_sati_active=sade_sati_active, sade_sati_phase=sade_sati_phase,
        jupiter_house=jupiter_house, saturn_house=saturn_house,
        rahu_house=rahu_house, ketu_house=ketu_house,
        ask_now_concern=ask_now_concern, language=language,
    )
    rows = query.order_by(User.id.asc()).all()
    return [row[0] for row in rows]


def get_user_detail(user_id: int) -> dict | None:
    """Real U2 basic identity/customer data, plus U3A's real (stored-
    only) Birth Astrology section -- Ask Now concern intelligence
    remains U3B+. Returns None for an unknown id (the route turns that
    into a 404, never a fabricated empty user).

    U4B.2 -- resolve_current_saturn_sign() is called EXACTLY ONCE per
    call to this function (this is itself a single HTTP request's worth
    of work) -- see list_users()'s own docstring for the same
    invariant. A resolution failure raises SadeSatiUnavailableError
    before any query runs.

    U4C.3 -- resolve_current_transit_snapshot() is ALSO called EXACTLY
    ONCE per call to this function, UNCONDITIONALLY (unlike list_users()'s
    lazy resolution) -- User Detail always exposes all 9
    TRANSIT_TRACKED_PLANETS' current rashi/house/degree/motion, so there
    is no "was it asked for" branch here. A resolution failure raises
    TransitUnavailableError before any query runs -- this function never
    silently returns a null/incorrect current_transits section. house is
    NULL for every planet whenever this user's Lagna is unavailable
    (never guessed) -- rashi/degree/motion are still returned regardless,
    since transit rashi is a GLOBAL fact, independent of this user's own
    natal chart (see this function's own return value below)."""
    try:
        saturn_resolution = resolve_current_saturn_sign()
    except Exception as exc:
        raise SadeSatiUnavailableError(str(exc)) from exc

    try:
        transit_snapshot = resolve_current_transit_snapshot()
    except Exception as exc:
        raise TransitUnavailableError(str(exc)) from exc

    columns, _ = _base_columns(saturn_resolution.saturn_sign)
    row = db.session.query(*columns).filter(User.id == user_id).first()
    if row is None:
        return None

    serialized = _serialize_row(row)

    # U4A.3 -- current_dasha is the WHOLE object, null (not a shell of
    # null fields) whenever there is no valid current row -- mahadasha
    # is never NULL on a genuine row (UserDashaTimeline.mahadasha is
    # NOT NULL in the schema), so its presence/absence alone tells us
    # whether a current row was found at all.
    current_dasha = None
    if serialized["current_mahadasha"] is not None:
        current_dasha = {
            "mahadasha": serialized["current_mahadasha"],
            "antardasha": serialized["current_antardasha"],
            "start_date": serialized["current_dasha_start_date"],
            "end_date": serialized["current_dasha_end_date"],
        }

    # U4B.2 -- sade_sati is null ONLY when natal Moon sign is
    # unavailable (NOT_CALCULATED) -- sade_sati_active is never NULL
    # for any other reason by the time serialization runs, since a
    # Saturn-resolution failure already raised SadeSatiUnavailableError
    # before this row was even queried.
    sade_sati = None
    if serialized["sade_sati_active"] is not None:
        sade_sati = {
            "active": serialized["sade_sati_active"],
            "phase": serialized["sade_sati_phase"],
        }

    # U4C.3 -- all 9 canonical transit bodies, from the ONE snapshot
    # resolved above. house uses THIS user's own lagna (serialized["lagna"],
    # already fetched via the existing firebase_uid bridge -- never
    # users.id == app_users.id) -- NULL whenever lagna is None (no
    # bridged AppUser, or Lagna never calculated) -- never guessed.
    # rashi/degree/motion are returned regardless of lagna availability,
    # since they describe the planet's GLOBAL current position, not
    # anything about this specific user's natal chart.
    # U5A -- Ask Now concern intelligence, read-only from Ask Now's own
    # existing, already-written history table (ask_now_intent_history --
    # no new storage). ONE fixed extra query for this single-user
    # request (never per-row, this function only ever serves one user
    # per call) -- ordered most-recent-first (created_at DESC, id DESC
    # as a deterministic tie-breaker for two rows sharing one
    # created_at). No FK on user_id (see that model's own docstring) --
    # this is a plain equality filter against the caller-supplied
    # `user_id`, which was already proven to belong to a real `User` row
    # by the query above (the `row is None` check already returned
    # None/404 otherwise) -- an orphaned history row for a DIFFERENT,
    # nonexistent user_id simply never matches this filter and can never
    # surface here. category/source/created_at are read VERBATIM --
    # never the raw question/answer (never stored to begin with, see
    # models_ask_now_intent_history.py's own privacy docstring) and
    # source is never inferred from ChatPack/payment state -- it is
    # Ask Now's own stored "free"/"pack" classification-time label.
    history_rows = (
        AskNowIntentHistory.query
        .filter(AskNowIntentHistory.user_id == user_id)
        .order_by(AskNowIntentHistory.created_at.desc(), AskNowIntentHistory.id.desc())
        .all()
    )
    concerns = [
        {
            "category": h.concern_category,
            "source": h.source,
            "created_at": h.created_at.isoformat() if h.created_at else None,
        }
        for h in history_rows
    ]
    # Optional category frequency summary (Section 10) -- derived in
    # Python from the SAME already-fetched rows above, zero extra query.
    category_counts: dict = {}
    for h in history_rows:
        category_counts[h.concern_category] = category_counts.get(h.concern_category, 0) + 1

    lagna = serialized["lagna"]
    current_transits = {
        "resolved_at": transit_snapshot.resolved_at,
        "planets": {
            planet: {
                "rashi": (pos := transit_snapshot.positions[planet])["rashi"],
                "house": calculate_house(lagna, pos["rashi"]) if lagna else None,
                "degree": pos.get("degree"),
                "motion": pos.get("motion"),
            }
            for planet in TRANSIT_TRACKED_PLANETS
        },
    }

    return {
        "identity": {
            "id": serialized["id"],
            "name": serialized["name"],
            "email": serialized["email"],
            "phone": serialized["phone"],
            "age": serialized["age"],
            "signup_date": serialized["signup_date"],
            "last_active_at": serialized["last_active_at"],
            "status": serialized["status"],
        },
        "customer": {
            "customer_type": serialized["customer_type"],
            "active_subscription": serialized["active_subscription"],
            "ask_now_buyer": serialized["ask_now_buyer"],
        },
        "birth_astrology": {
            "moon_sign": serialized["moon_sign"],
            "lagna": serialized["lagna"],
            "nakshatra": serialized["nakshatra"],
            "nakshatra_pada": serialized["nakshatra_pada"],
            # Full stored JSONB, verbatim -- None (uncalculated), {}
            # (calculated, none active/present), or the sparse
            # {"<canonical_key>": {"strength"/"severity": ...}} object.
            # No prose, no reasons/positives/challenge/description/
            # remedies/upsell (never stored there to begin with).
            "static_yog": serialized["static_yog"],
            "static_dosh": serialized["static_dosh"],
            "static_astrology_calculated_at": serialized["static_astrology_calculated_at"],
            "static_astrology_version": serialized["static_astrology_version"],
            # U4A.3 -- read-only, from the persisted UserDashaTimeline
            # ONLY. Never all 81 rows -- only the single row that is
            # CURRENT right now (or null). Never recalculated.
            "current_dasha": current_dasha,
            # U4B.2 -- read-only, from persisted moon_sign + the one
            # resolved current Saturn sign. Never phase_dates, never
            # start/end dates -- U4B v1 exposes active+phase only.
            "sade_sati": sade_sati,
            # U4C.3 -- read-only, from the ONE current transit snapshot
            # resolved above + this user's own persisted lagna. Never
            # persisted, never a per-planet ephemeris call. All 9
            # canonical bodies, always present (never opt-in, unlike
            # the Admin list filters) -- house is null per-planet only
            # when lagna itself is unavailable.
            "current_transits": current_transits,
        },
        # U5A -- Ask Now concern intelligence (category/source/timestamp
        # only -- never raw question/answer text, which does not exist
        # in storage to begin with). `buyer` mirrors the SAME corrected
        # _ask_now_buyer_expr() used above in `customer.ask_now_buyer` --
        # one definition, never two. Empty history (no Ask Now activity
        # at all) is a normal, successful response -- total_classified_
        # questions: 0, concerns: [], never a 404 (see this function's
        # own None-check above, which only ever fires for a genuinely
        # unknown user id).
        "ask_now": {
            "buyer": serialized["ask_now_buyer"],
            "total_classified_questions": len(concerns),
            "concerns": concerns,
            "category_counts": category_counts,
        },
    }
