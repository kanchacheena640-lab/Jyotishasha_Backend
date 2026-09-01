# modules/services/chatpack_google_verify.py

"""
Google Play ChatPack Verify -- HARDENED (Ask Now: asknow8q + asknow10q)

History: Phase-1 of this file trusted the client-supplied purchase_token
outright ("no Google API call yet") and ignored product_id entirely,
always granting a fixed 8-question/₹51 pack. An audit of this file
proved three defects: (1) no real Google Play verification, (2)
product_id ignored, (3) the same purchase_token could create multiple
ChatPack rows. This version fixes all three, without introducing a
second Google-auth mechanism and without any schema change.

==================================================
PRODUCT MAPPING (business contract)
==================================================
    asknow8q  -> 8 questions / ₹51   (legacy -- MUST remain valid for
                 old/pending purchases already in flight; unchanged
                 from the original behavior)
    asknow10q -> 10 questions / ₹100 (new Ask Now product)
Any other product_id is rejected outright -- never silently mapped to
asknow8q or any other entry.

==================================================
GOOGLE PLAY VERIFICATION (reused, not reimplemented)
==================================================
Calls modules/payments/google_play_provider.py's
GooglePlayProvider.verify_product_purchase() -- the SAME one-time
consumable-product verification (purchases.products.get) already used
by Premium PDF Reports (routes_google_report_confirm.py). This file
adds zero new Google credentials/session/auth code; it reuses the
existing get_android_publisher_session()/GOOGLE_PLAY_PACKAGE_NAME
plumbing exactly as that caller does. package_name is never
client-supplied -- always the server's own configured
GOOGLE_PLAY_PACKAGE_NAME (verify_product_purchase()'s own default).

A purchase is accepted only when BOTH:
  - verification_status == VERIFIED (Google has a real record of this
    exact purchase_token FOR this exact product_id -- Google's own
    purchases.products.get URL is keyed by productId, so a token that
    actually belongs to a different product 404s as NOT_FOUND here,
    with no extra cross-check needed), AND
  - purchase_state == 0 ("Purchased" -- see google_play_models.py's own
    docstring: 0=Purchased, 1=Canceled, 2=Pending). A cancelled or
    still-pending purchase is rejected, exactly like
    GooglePlayProvider._verify_report_purchase()'s own existing
    purchaseState gate for Reports.

==================================================
IDEMPOTENCY (application-level, existing ChatPack storage)
==================================================
Before doing anything else -- including before calling Google, so a
retry of an already-processed token costs nothing -- this file looks
up an existing status="success" ChatPack row for this exact
purchase_token (stored in razorpay_payment_id). If found, it returns
the SAME success-shaped response a first-time call would return,
granting nothing new. This is what makes a network retry / app
restart / restorePurchases redelivery safe for Flutter's
autoConsume:false -> verify -> consume flow: consume() is safe to call
again on a purchase Google already considers consumed/acknowledged,
and the backend will not grant a second pack for it.

KNOWN RESIDUAL RISK (disclosed, not fixed here -- see this task's own
"do not casually modify schema" instruction): this is a check-then-
insert pattern, not a database-enforced constraint.
`chat_packs.razorpay_payment_id` has no UNIQUE constraint. Two
genuinely CONCURRENT requests for the same token, both passing the
"not found yet" lookup before either commits, could still both insert
a row. Flutter's own actual call pattern (sequential retries after a
prior call didn't get an answer, not parallel duplicate submissions)
makes this narrow window unlikely to matter in practice, but it is not
airtight. Fully closing it would require a migration adding a unique
constraint on razorpay_payment_id -- not created here; see the
verification report for why.
"""

import hashlib
import logging
from datetime import datetime, timezone

from extensions import db
from modules.models_chat_pack import ChatPack
from modules.payments.google_play_models import GooglePlayVerificationStatus
from modules.payments.google_play_provider import GooglePlayProvider

# Phase 4B -- the existing, unmodified Phase-2 ledger write path. This
# import introduces no circular dependency: modules.activity_events.*
# imports nothing from modules.services.
from modules.activity_events.service import record_event

_activity_events_logger = logging.getLogger("activity_events")

# Phase 4B -- same analytics-only purpose literal chat_pack_service.py
# uses for the Razorpay Ask Now path -- both are the same product
# (ChatPack), just a different provider. Not added to PaymentPurpose
# (see chat_pack_service.py's own comment on why).
_PAYMENT_PURPOSE_CHATPACK = "ASK_NOW_CHAT_PACK"

# Phase 4B -- maps GooglePlayVerificationStatus to the frozen FAILURE_
# REASONS vocabulary (modules/activity_events/event_schemas.py). Same
# mapping payment_service.py uses for the shared PaymentService flows
# -- kept as a second, tiny, explicit local copy rather than importing
# from modules.payments.payment_service, per the Phase 4B design
# freeze's instruction to prefer a few explicit local lines over
# expanding file scope for a fourth production file.
_GOOGLE_FAILURE_REASON_BY_VERIFICATION_STATUS = {
    GooglePlayVerificationStatus.INVALID_TOKEN: "invalid_input",
    GooglePlayVerificationStatus.NOT_FOUND: "not_found",
    GooglePlayVerificationStatus.AUTH_ERROR: "upstream_error",
    GooglePlayVerificationStatus.NETWORK_ERROR: "upstream_error",
    GooglePlayVerificationStatus.UNKNOWN_ERROR: "unknown",
}


def _hash_google_purchase_token(purchase_token: str) -> str:
    """Deterministic, one-way identifier for Google Play's
    purchase_token -- see payment_service.py's own docstring for why
    this must never reach activity_events in raw form. Stdlib hashlib
    only; no new dependency, no new crypto abstraction."""
    return hashlib.sha256(purchase_token.encode("utf-8")).hexdigest()


def _emit_chatpack_event(
    *,
    event_name,
    entity_id=None,
    order_reference=None,
    failure_reason=None,
    amount=None,
    currency=None,
    dedupe_key=None,
):
    """Phase 4B -- observational only, called ONLY after this module's
    own authoritative ChatPack commit for the request has already
    completed (see each call site). record_event() (Phase 2,
    unmodified) already guarantees it never raises and never touches
    db.session; this helper is additionally wrapped in its own
    try/except so an unexpected error in the small amount of dict-
    building above can never propagate back into a caller whose
    ChatPack result has already been decided. profile_id/firebase_uid
    are always None here -- ChatPack.user_id is users.id, not
    app_users.id, and activity_events has no users.id column; no
    identity bridge is introduced (LOCKED DECISION, Phase 4B design
    freeze). correlation_id is always None -- this module has no
    correlation_id concept, and none is invented here."""
    properties = {"purpose": _PAYMENT_PURPOSE_CHATPACK, "provider": "GOOGLE_PLAY"}
    if order_reference is not None:
        properties["order_reference"] = order_reference
    if failure_reason is not None:
        properties["failure_reason"] = failure_reason
    if amount is not None:
        properties["amount"] = amount
    if currency is not None:
        properties["currency"] = currency

    try:
        record_event(
            event_name=event_name,
            occurred_at=datetime.now(timezone.utc),
            platform="backend_internal",
            source="chatpack_google_verify",
            firebase_uid=None,
            profile_id=None,
            correlation_id=None,
            entity_type="chat_pack" if entity_id is not None else None,
            entity_id=str(entity_id) if entity_id is not None else None,
            properties=properties,
            dedupe_key=dedupe_key,
        )
    except Exception:
        _activity_events_logger.warning(
            "chatpack_google_verify: unexpected error emitting %s "
            "(swallowed -- the ChatPack result already decided is "
            "unaffected)",
            event_name, exc_info=True,
        )

# Google Play purchaseState values for a one-time product (raw ints --
# see google_play_models.py's own docstring): 0=Purchased, 1=Canceled,
# 2=Pending. Only a genuinely completed, paid purchase may grant
# entitlement. Kept as this file's own local constant (rather than
# reaching into GooglePlayProvider's private _PRODUCT_PURCHASED_STATE)
# since it documents the same public Google contract, not an
# implementation detail of that class.
_PRODUCT_PURCHASED_STATE = 0

# Explicit whitelist -- the ONLY product_ids this endpoint will ever
# grant entitlement for. Unknown product_id -> rejected, never
# defaulted to asknow8q or any other entry.
CHATPACK_PRODUCT_MAP = {
    "asknow8q": {"amount": 51, "questions_total": 8},
    "asknow10q": {"amount": 100, "questions_total": 10},
}


def verify_google_chatpack(user_id: int, product_id: str, purchase_token: str):
    """
    Verify a Google Play ChatPack purchase and activate entitlement.

    Response shape (unchanged from before this hardening, so Flutter's
    existing autoConsume:false -> verify -> consume flow needs no
    change):
        Success (first-time OR idempotent replay of an
        already-processed token):
            {"success": True, "remaining_tokens": N, "message": "..."}
        Rejected (nothing granted -- Flutter must NOT consume the
        purchase in this case):
            {"success": False, "error": "<code>", "message": "..."}
    """
    if not user_id or not product_id or not purchase_token:
        return {
            "success": False,
            "error": "missing_fields",
            "message": "Missing required fields",
        }

    product = CHATPACK_PRODUCT_MAP.get(product_id)
    if product is None:
        return {
            "success": False,
            "error": "unknown_product",
            "message": f"Unrecognized product_id: {product_id!r}",
        }

    # ---- Idempotency -- checked first, before any Google API call ----
    existing = ChatPack.query.filter_by(
        razorpay_payment_id=purchase_token, status="success",
    ).first()
    if existing is not None:
        # Phase 4B -- payment_duplicate_ignored: this backend already,
        # truthfully, applied no new business effect for this token --
        # dedupe_key intentionally NULL (each occurrence is its own ops
        # signal, never counted as a revenue conversion). Confirmed
        # separately (Phase 4B design freeze, Step 1): this only
        # protects the analytics ledger from a second row -- it does
        # NOT repair the underlying check-then-insert business race
        # this module's own docstring already discloses.
        _emit_chatpack_event(
            event_name="payment_duplicate_ignored",
            entity_id=existing.id,
        )
        return {
            "success": True,
            "remaining_tokens": existing.remaining_questions(),
            "message": "Purchase already verified -- ChatPack already active",
            "already_processed": True,
        }

    # ---- Real Google Play verification (reused, not reimplemented) ----
    verification = GooglePlayProvider().verify_product_purchase(
        purchase_token=purchase_token, product_id=product_id,
    )

    if verification.verification_status != GooglePlayVerificationStatus.VERIFIED:
        # Phase 4B -- payment_failed. Classified from verification.
        # verification_status (a structured enum value), never
        # verification.error_message (provider-ish free text).
        # dedupe_key intentionally NULL. No ChatPack row exists yet at
        # this point, so no entity is attached.
        _emit_chatpack_event(
            event_name="payment_failed",
            failure_reason=_GOOGLE_FAILURE_REASON_BY_VERIFICATION_STATUS.get(
                verification.verification_status, "unknown",
            ),
        )
        return {
            "success": False,
            "error": "verification_failed",
            "message": (
                verification.error_message
                or f"Google Play verification failed: {verification.verification_status}"
            ),
        }

    if verification.purchase_state != _PRODUCT_PURCHASED_STATE:
        # Phase 4B -- payment_failed. Google has a real record of this
        # token (verification_status == VERIFIED) but declined to
        # complete it (Canceled/Pending) -- "provider_declined", per
        # the Phase 4B design freeze's exact mapping. No raw
        # purchase_state int or message text stored.
        _emit_chatpack_event(
            event_name="payment_failed",
            failure_reason="provider_declined",
        )
        return {
            "success": False,
            "error": "purchase_not_completed",
            "message": (
                f"Purchase is not in a completed/purchased state "
                f"(purchaseState={verification.purchase_state!r})."
            ),
        }

    # ---- Grant entitlement -- product-specific amount/questions ----
    pack = ChatPack(
        user_id=user_id,
        amount=product["amount"],
        questions_total=product["questions_total"],
        questions_used=0,
        status="success",
        razorpay_order_id=verification.order_id or f"GP_{product_id}",
        razorpay_payment_id=purchase_token,
        verified_at=datetime.utcnow(),
    )

    db.session.add(pack)
    db.session.commit()

    # Phase 4B -- payment_verified: fired strictly after the success
    # commit above. purchase_token is NEVER placed into dedupe_key
    # directly -- only its sha256 hash (deterministic, one-way).
    # order_reference uses Google's own order_id (never the token) and
    # is simply omitted when Google didn't return one.
    _emit_chatpack_event(
        event_name="payment_verified",
        entity_id=pack.id,
        order_reference=verification.order_id,
        amount=product["amount"],
        currency="INR",
        dedupe_key=f"payment_verified:GOOGLE_PLAY:CHATPACK:{_hash_google_purchase_token(purchase_token)}",
    )

    remaining = pack.questions_total - pack.questions_used

    return {
        "success": True,
        "remaining_tokens": remaining,
        "message": "Google Play ChatPack activated",
    }
