# routes/routes_google_purchase_confirm.py

"""
Google Purchase Confirmation API -- Subscription Purchase System, S9
(endpoint) + S14 (authentication) + S16 (information exposure).

The missing piece the S8 audit's finding C-1 named: PaymentService,
GooglePlayProvider, SubscriptionPurchaseMappingService, and the whole
S3-S7E chain were fully built and unit-tested, but reachable only from
a Python test script -- no HTTP route ever let a Flutter client submit
a completed Google Play purchase for verification/activation. This
file is that route, and nothing else:

    Flutter (authenticated)
        │
        ▼
    POST /api/subscription/google/confirm   -- @jwt_required()
        │  resolve profile_id from the JWT identity (S14) -- never
        │  from the request body -- then parse + validate the rest
        ▼
    Build PaymentRequest
        │
        ▼
    PaymentService.process_payment()   -- unmodified; already does
        │                                  verify -> idempotency claim
        │                                  -> _apply_subscription_
        │                                  business_effect() -> mapping
        │                                  upsert -> activate_subscription
        ▼
    Return structured result

GooglePlayProvider, the RTDN dispatcher/endpoint, ProcessedSubscriptionEvent,
EntitlementWriteService, and Apple are all untouched -- this file only
translates one HTTP request into one PaymentRequest and one
PaymentVerificationResult back into HTTP, exactly like app.py's
existing /webhook route already does for Razorpay.

Authentication (S13 audit finding C-1, fixed here): this endpoint
previously trusted `profile_id` directly from the request body, with
no verification that the caller was authorized to act on that profile
-- a real cross-account entitlement-hijack vector. Fixed by reusing
the project's existing, already-proven pattern for exactly this
situation -- @jwt_required() + get_jwt_identity() +
resolve_profile_id_from_account_user_id() (modules/subscription/
dual_write_adapter.py) -- the same three calls already used by
modules/auth/routes_profile.py::subscription_info() and
modules/subscription/routes.py. No new authentication mechanism was
introduced. profile_id in the request body is now optional and, if
present, is only ever compared against the authenticated identity's
own resolved profile_id -- a mismatch is rejected (403) as a
cross-account attempt, never silently substituted or trusted.

platform is validated here (ANDROID/GOOGLE_PLAY only) and rejected
otherwise -- Apple is a separate, unimplemented phase, and this
endpoint must not silently attempt to route an iOS purchase through
GooglePlayProvider.

product_id is accepted in the request body (as the task's own contract
requires) but is NOT trusted for the plan-mapping decision -- that
decision is already made inside PaymentService, and it can only be
based on Google's OWN verified product_id (verification_result.
raw_payload["product_id"]), never a client-supplied value. The
client's product_id is carried through only in PaymentRequest.metadata
for logging/traceability.

selected_segment (Subscription Purchase System -- S12) is REQUEST-shape
validated here only -- is the string one of SUBSCRIPTION_SECTIONS
(modules/entitlement/subscription_sections.py -- the six selectable
subscription sections, including Alerts & Opportunities; deliberately
NOT AI_REPORT_SEGMENTS, which is the AI Report Engine's own, narrower,
5-value generation domain -- see that file's own docstring). Whether
a given purchase's plan actually REQUIRES one is a business rule this
route does not know and does not duplicate: that decision already lives
entirely inside EntitlementWriteService's existing, unmodified
ACCESS_SELECTED/ACCESS_ALL check (modules/entitlement/
plan_access_policy.py), which only runs once PaymentService has
resolved the plan from Google's own verified product_id. So this route
only rejects a syntactically-invalid segment (400); an OMITTED segment
is passed through as None and is either fine (ACCESS_ALL plans -- Gold/
Gold+/Platinum) or surfaces as a structured ACTIVATION_FAILED business
outcome (ACCESS_SELECTED plans -- Silver/Silver+), exactly as
EntitlementWriteService already decides for every other caller.

HTTP status convention -- matches app.py's existing /webhook route
exactly, rather than inventing a new one:
    401 -- missing/invalid/expired JWT. Handled entirely by
           @jwt_required()'s own, already-configured error handling --
           nothing new added in this file.
    403 -- the authenticated account has no resolvable profile, or the
           request named a profile_id belonging to a different account.
    400 -- the HTTP request itself is malformed/missing required
           fields, or names an unsupported platform. Also used for
           PaymentStatus.FAILED when Google's own verification_status
           is a genuine, client-caused rejection (INVALID_TOKEN /
           NOT_FOUND) -- Google itself rejected this exact token.
    503 -- PaymentStatus.FAILED for every OTHER verification_status
           (AUTH_ERROR / NETWORK_ERROR / UNKNOWN_ERROR) -- an
           infrastructure-shaped failure on this backend's own side
           (S16, S13 audit finding H-3). The client only ever sees a
           generic "temporarily unavailable" message; the real reason
           is already captured server-side by PaymentService's own
           verification_result log line -- never returned here.
    200 -- PaymentStatus.VERIFIED or PaymentStatus.DUPLICATE. VERIFIED
           always carries the real SubscriptionPurchaseResult outcome
           in the body (ACTIVATED / PENDING / NOT_ACTIVATED /
           UNMAPPED_PRODUCT / ACTIVATION_FAILED) -- these are
           legitimate, structured business outcomes, not request
           errors, so the client can branch on `outcome` rather than
           on the HTTP status.
    500 -- an unexpected exception. Never leaks the raw exception,
           same as /webhook.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from modules.entitlement.subscription_sections import SUBSCRIPTION_SECTIONS
from modules.payments import (
    PaymentProviderType,
    PaymentPurpose,
    PaymentRequest,
    PaymentService,
    PaymentStatus,
)
from modules.payments.google_play_models import GooglePlayVerificationStatus
from modules.payments.payment_logger import log_payment_event, new_correlation_id

routes_google_purchase_confirm = Blueprint("routes_google_purchase_confirm", __name__)

# Platform values this endpoint accepts as "this is a Google Play
# purchase" -- Apple is a separate, unimplemented phase (see this
# module's own docstring).
_GOOGLE_PLAY_PLATFORMS = ("ANDROID", "GOOGLE_PLAY")

# S16 -- verification_status values that represent a genuine, client-
# caused rejection (the token itself is invalid/unknown to Google) --
# safe to return verbatim. Everything else (AUTH_ERROR, NETWORK_ERROR,
# UNKNOWN_ERROR) is an infrastructure-shaped failure on this backend's
# own side and must never be described to the client.
_CLIENT_SAFE_VERIFICATION_STATUSES = (
    GooglePlayVerificationStatus.INVALID_TOKEN,
    GooglePlayVerificationStatus.NOT_FOUND,
)


def _bad_request(message: str):
    return jsonify({"status": "INVALID_REQUEST", "message": message}), 400


@routes_google_purchase_confirm.route("/api/subscription/google/confirm", methods=["POST"])
@jwt_required()
def confirm_google_purchase():
    # S14 -- profile_id is resolved from the authenticated JWT identity,
    # exactly the way modules/auth/routes_profile.py::subscription_info()
    # and modules/subscription/routes.py already do (same import, same
    # call, not reinvented here). profile_id is never trusted from the
    # request body for the actual operation -- see the cross-account
    # check below.
    from modules.subscription.dual_write_adapter import (
        resolve_profile_id_from_account_user_id,
    )

    user_id = get_jwt_identity()
    authenticated_profile_id = resolve_profile_id_from_account_user_id(user_id)
    if authenticated_profile_id is None:
        return jsonify({
            "status": "FORBIDDEN", "message": "No profile is associated with this account.",
        }), 403

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _bad_request("Request body must be a JSON object.")

    purchase_token = data.get("purchase_token")
    if not purchase_token or not isinstance(purchase_token, str):
        return _bad_request("purchase_token is required.")

    platform = data.get("platform")
    if not platform or platform.upper() not in _GOOGLE_PLAY_PLATFORMS:
        return _bad_request(
            f"platform must be one of {_GOOGLE_PLAY_PLATFORMS!r} -- Apple is not implemented."
        )

    # profile_id is no longer required from the client -- the
    # authenticated identity above is always the one actually used. If
    # the request still names one (older client, or wire compatibility),
    # it must match the authenticated owner's own profile; anything else
    # is a cross-account attempt and is rejected outright rather than
    # silently corrected.
    profile_id_raw = data.get("profile_id")
    if profile_id_raw is not None:
        try:
            requested_profile_id = int(profile_id_raw)
        except (TypeError, ValueError):
            return _bad_request("profile_id must be an integer.")
        if requested_profile_id != authenticated_profile_id:
            return jsonify({
                "status": "FORBIDDEN",
                "message": "profile_id does not belong to the authenticated account.",
            }), 403

    profile_id = authenticated_profile_id

    product_id = data.get("product_id")

    # selected_segment (S12) -- optional at the request level (whether
    # it's actually REQUIRED depends on the plan, resolved later inside
    # PaymentService from Google's own verified product_id, not decided
    # here). Only reject a value that isn't one of the six canonical
    # segments at all; omission is not a request error.
    selected_segment_raw = data.get("selected_segment")
    selected_segment = None
    if selected_segment_raw is not None:
        if not isinstance(selected_segment_raw, str):
            return _bad_request("selected_segment must be a string.")
        selected_segment = selected_segment_raw.strip().upper()
        if selected_segment not in SUBSCRIPTION_SECTIONS:
            return _bad_request(
                f"selected_segment must be one of {SUBSCRIPTION_SECTIONS!r}."
            )

    payment_request = PaymentRequest(
        provider=PaymentProviderType.GOOGLE_PLAY,
        purpose=PaymentPurpose.SUBSCRIPTION,
        reference=purchase_token,
        payment_id=purchase_token,
        profile_id=profile_id,
        selected_segment=selected_segment,
        metadata={"product_id_from_client": product_id} if product_id else {},
    )

    correlation_id = new_correlation_id()
    log_ctx = dict(
        correlation_id=correlation_id, provider=PaymentProviderType.GOOGLE_PLAY,
        product=product_id, razorpay_order_id=purchase_token, razorpay_payment_id=purchase_token,
    )

    try:
        result = PaymentService().process_payment(payment_request)
    except Exception as exc:
        log_payment_event(
            "google_purchase_confirm_failed", status="FAILED",
            error=str(exc), exc_info=True, **log_ctx,
        )
        return jsonify({
            "status": "ERROR", "message": "Internal error processing this purchase.",
        }), 500

    if result.status == PaymentStatus.FAILED:
        # S16 -- never return an internal-infrastructure-shaped failure
        # (our own credentials/config missing, a network problem
        # reaching Google, or anything unclassified) verbatim to the
        # client -- see this module's docstring. Google's own
        # verification_status already distinguishes a genuinely
        # client-caused rejection (the token itself is invalid/not
        # found) from everything else; this only changes what gets
        # returned here, not anything PaymentService/GooglePlayProvider
        # computed. The detailed reason is already logged server-side
        # by PaymentService.process_payment()'s own, unmodified
        # verification_result log line -- nothing new to log here.
        verification_status = (result.raw_payload or {}).get("verification_status")
        if verification_status in _CLIENT_SAFE_VERIFICATION_STATUSES:
            return jsonify({"status": "FAILED", "message": result.message}), 400
        return jsonify({
            "status": "TEMPORARILY_UNAVAILABLE",
            "message": "Purchase verification is temporarily unavailable. Please try again shortly.",
        }), 503

    if result.status == PaymentStatus.DUPLICATE:
        return jsonify({"status": "DUPLICATE", "message": result.message}), 200

    # PaymentStatus.VERIFIED -- raw_payload is the SubscriptionPurchaseResult
    # dict process_payment() attached (outcome/activated/purchase_state/
    # plan/provider_order_id/message), untouched by this route.
    body = {"status": "VERIFIED", **(result.raw_payload or {})}
    return jsonify(body), 200
