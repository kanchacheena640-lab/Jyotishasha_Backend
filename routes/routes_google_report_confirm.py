# routes/routes_google_report_confirm.py

"""
Google Play One-Time Product Confirmation API -- Premium PDF Reports.

The Google Play counterpart to app.py's existing /webhook route: that
route is Razorpay's entry point into PaymentService for a report
purchase; this file is the same entry point for a Google Play
one-time-product purchase (e.g. the "reports51" consumable). Nothing
else changes -- same PaymentService, same PaymentPurpose.REPORT_PURCHASE
business effect, same OrderService, same generation pipeline.

    Flutter (Google Play consumable purchase)
        |
        v
    POST /api/reports/google/confirm
        |  validate request shape only -- no business logic lives here
        v
    Build PaymentRequest(provider=GOOGLE_PLAY, purpose=REPORT_PURCHASE)
        |
        v
    PaymentService.process_payment()   -- unmodified; already does
        |                                  verify -> idempotency claim ->
        |                                  OrderService.create_paid_report_order()
        v
    Return structured result

GooglePlayProvider, PaymentService, OrderService, tasks.py, and the
PDF/email pipeline are all untouched by this file -- it only translates
one HTTP request into one PaymentRequest and one
PaymentVerificationResult back into HTTP, exactly like app.py's
existing /webhook route already does for Razorpay.

Not authenticated with a backend JWT, matching /webhook's own existing
contract for report purchases (unlike /api/subscription/google/confirm,
which requires one because it must resolve a profile_id) -- the
report's identity comes entirely from order_payload's own fields
(name/email/product/dob/tob/pob), the same shape /webhook already
accepts, unauthenticated, from the Website today.

product_id is required here (unlike /api/subscription/google/confirm,
where it is optional/log-only) because GooglePlayProvider's one-time-
product verification needs it to build the Google Play Developer API
URL itself (purchases.products.get is keyed by productId, unlike the
subscriptions endpoint) -- see GooglePlayProvider._verify_report_
purchase() for where it is actually used.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from modules.payments import (
    PaymentProviderType,
    PaymentPurpose,
    PaymentRequest,
    PaymentService,
    PaymentStatus,
)
from modules.payments.google_play_models import GooglePlayVerificationStatus

routes_google_report_confirm = Blueprint("routes_google_report_confirm", __name__)

# Same required-field set OrderService.create_paid_report_order() itself
# enforces -- checked here too only so a malformed request gets a clear
# 400 instead of surfacing as a generic 500 from deeper in the pipeline.
_REQUIRED_ORDER_FIELDS = ("name", "email", "product")

# Fields forwarded into order_payload -- the exact same field set
# app.py's /webhook route already reads from the client today.
_ORDER_PAYLOAD_FIELDS = (
    "name", "email", "phone", "product", "dob", "tob", "pob",
    "latitude", "longitude", "language", "partner",
)


def _bad_request(message: str):
    return jsonify({"error": message}), 400


@routes_google_report_confirm.route("/api/reports/google/confirm", methods=["POST"])
def confirm_google_report_purchase():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _bad_request("Request body must be a JSON object.")

    purchase_token = data.get("purchase_token")
    if not purchase_token or not isinstance(purchase_token, str):
        return _bad_request("purchase_token is required.")

    product_id = data.get("product_id")
    if not product_id or not isinstance(product_id, str):
        return _bad_request("product_id is required.")

    missing = [field for field in _REQUIRED_ORDER_FIELDS if not data.get(field)]
    if missing:
        return _bad_request(f"Missing required field(s): {', '.join(missing)}")

    order_payload = {
        key: data.get(key) for key in _ORDER_PAYLOAD_FIELDS if data.get(key) is not None
    }

    payment_request = PaymentRequest(
        provider=PaymentProviderType.GOOGLE_PLAY,
        purpose=PaymentPurpose.REPORT_PURCHASE,
        reference=purchase_token,
        payment_id=purchase_token,
        order_payload=order_payload,
        # product_id is required (unlike the subscription-confirm route's
        # optional, log-only product_id_from_client) -- GooglePlayProvider
        # reads it from here to build the purchases.products.get URL.
        metadata={"product_id": product_id},
    )

    try:
        result = PaymentService().process_payment(payment_request)
    except Exception:
        # Never leak an unhandled exception as Flask's default 500 page --
        # same policy as app.py's /webhook route. PaymentService has
        # already logged the full, correlated failure before this
        # exception reached us.
        return jsonify({"error": "Internal error processing this purchase."}), 500

    if result.status not in (PaymentStatus.VERIFIED, PaymentStatus.DUPLICATE):
        # Report Purchase CANCELED Recovery Dead-End fix: the data below
        # already exists on every REPORT_PURCHASE verification failure --
        # GooglePlayProvider._verify_report_purchase() sets raw_payload=
        # result.to_dict() unconditionally, both on success and failure
        # (see GooglePlayProductVerification.to_dict()) -- it just wasn't
        # surfaced past this route before. Additive fields only; `error`
        # and `message` are unchanged so any existing client that only
        # reads those two keeps working exactly as before.
        raw = result.raw_payload or {}
        verification_status = raw.get("verification_status")
        purchase_state = raw.get("purchase_state")

        # Only Google's own TERMINAL verdict on this exact token --
        # verification_status VERIFIED (Google definitely has a record
        # of it) AND purchase_state == 1 (Canceled) -- may ever tell a
        # client this purchase can never succeed. Everything else
        # (AUTH_ERROR, NETWORK_ERROR, NOT_FOUND/propagation delay,
        # UNKNOWN_ERROR, or a still-Pending purchase) must stay
        # classified as retryable, or as "pending" (also not terminal,
        # but not identical to a plain retryable failure either) --
        # never as canceled.
        if verification_status == GooglePlayVerificationStatus.VERIFIED and purchase_state == 1:
            error_code = "purchase_canceled"
        elif verification_status == GooglePlayVerificationStatus.VERIFIED and purchase_state == 2:
            error_code = "purchase_pending"
        else:
            error_code = "verification_failed"

        return jsonify({
            "error": "Payment verification failed",
            "message": result.message,
            "error_code": error_code,
            "verification_status": verification_status,
            "purchase_state": purchase_state,
        }), 400

    if not result.raw_payload:
        # Extremely narrow race window: a concurrent request for the same
        # payment_id is still finishing its own processing right now --
        # same handling as app.py's /webhook route.
        return jsonify({"message": "Payment already being processed"}), 200

    order_id = result.raw_payload.get("order_id")
    task_id = result.raw_payload.get("task_id")

    if task_id is not None:
        return jsonify({
            "message": "Purchase verified -- report task queued",
            "order_id": order_id,
            "task_id": task_id,
        }), 200
    else:
        return jsonify({
            "message": "Purchase verified -- report generation started",
            "order_id": order_id,
        }), 200
