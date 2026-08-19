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

from datetime import datetime

from extensions import db
from modules.models_chat_pack import ChatPack
from modules.payments.google_play_models import GooglePlayVerificationStatus
from modules.payments.google_play_provider import GooglePlayProvider

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
        return {
            "success": False,
            "error": "verification_failed",
            "message": (
                verification.error_message
                or f"Google Play verification failed: {verification.verification_status}"
            ),
        }

    if verification.purchase_state != _PRODUCT_PURCHASED_STATE:
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

    remaining = pack.questions_total - pack.questions_used

    return {
        "success": True,
        "remaining_tokens": remaining,
        "message": "Google Play ChatPack activated",
    }
