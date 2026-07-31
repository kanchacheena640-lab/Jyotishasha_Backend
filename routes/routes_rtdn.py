# routes/routes_rtdn.py

"""
Google Play RTDN (Real-Time Developer Notifications) HTTP endpoint --
Subscription Purchase System, S7C (endpoint) + S7D (authentication) +
S7E (identity resolution).

This file does ONLY what a Google Cloud Pub/Sub push subscription
needs on the receiving end:
    0. Authenticate the request -- PubSubAuthService.verify_request()
       (S7D), gating everything below. Only a request Google Cloud
       Pub/Sub itself signed (an OIDC bearer token verified against
       Google's own public keys) may reach parsing/dispatch at all.
    1. Parse the Pub/Sub push envelope (`{"message": {...}, "subscription": ...}`).
    2. Base64-decode `message.data` into Google Play's own RTDN JSON.
    3. Identify the notification -- either `subscriptionNotification`
       (map its numeric `notificationType` to the string name
       SubscriptionService.process_webhook_event() already expects) or
       `testNotification`.
    4. Resolve profile_id -- SubscriptionPurchaseMappingService.
       resolve_profile_id() (S7E), looking up the purchase_token
       against the mapping PaymentService recorded at purchase time
       (falling back to a linked_purchase_token lookup for a
       replaced/upgraded token). A bare purchase_token this system
       genuinely never saw resolves to None -- a legitimate, honest
       outcome, not an error.
    5. Call SubscriptionService.process_webhook_event() -- the S7B
       dispatcher, unmodified. All verification, idempotency
       (ProcessedSubscriptionEvent), and entitlement dispatch logic
       live there; this file never touches any of it. An unresolved
       profile_id is passed through as None, and the dispatcher's own
       MISSING_PROFILE_ID outcome reports that rather than guessing.
    6. Translate the outcome into the HTTP status Pub/Sub needs to
       decide whether to redeliver.

HTTP response contract (what decides Pub/Sub redelivery):
    401 -- the request itself did not authenticate (see
           PubSubAuthStatus for every specific reason) -- checked
           before anything else. A request Pub/Sub never actually sent
           will never authenticate on retry either, but 401 (rather
           than 200) keeps this failure loud/visible rather than
           silently swallowed.
    400 -- envelope/payload could not be parsed or is missing required
           fields. Not Google's fault to retry; a malformed message
           won't become parseable on redelivery.
    200 -- notification was successfully handed to the dispatcher and
           it returned a structured result -- success or a structured
           business failure (MISSING_PROFILE_ID, VERIFICATION_FAILED,
           UNMAPPED_PRODUCT, ...). Retrying would not change a
           structured outcome, so there is nothing to gain from a
           redelivery; Pub/Sub should not resend this message. Also
           used for an unrecognized numeric notificationType (a future
           Google enum value this code does not know about yet --
           logged, ignored, acknowledged).
    500 -- the dispatcher raised (a genuine infrastructure failure, or
           the deliberate NotImplementedError for SUBSCRIPTION_PAUSED/
           SUBSCRIPTION_RESTARTED). Pub/Sub's own retry/backoff is
           exactly what should happen here: an infra failure may
           succeed on retry, and the ledger claim for PAUSED/RESTARTED
           is deliberately left unfinished (S7B) so a future
           redelivery, once those two are implemented, can still
           succeed.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import uuid
from typing import Any, Dict, Optional, Tuple

from flask import Blueprint, jsonify, request

from modules.payments.payment_logger import _mask_identifier
from modules.payments.pubsub_auth_service import PubSubAuthService
from modules.payments.subscription_purchase_mapping_service import (
    SubscriptionPurchaseMappingService,
)
from modules.subscription.subscription_service import SubscriptionService

routes_rtdn = Blueprint("routes_rtdn", __name__)

# ------------------------------------------------------------
# Structured logging -- same single-line-JSON-via-stdlib-logging shape
# as modules/payments/payment_logger.py, with RTDN's own fields
# instead of payment_logger's Razorpay-shaped ones (reusing that
# module directly would force irrelevant None fields into every line).
#
# S18: purchase_token is masked via the same _mask_identifier()
# payment_logger.py already uses -- reused here, not reimplemented, so
# there is exactly one masking algorithm in this codebase rather than
# two that could drift apart. This closes the gap S16 left: that
# phase only masked payment_logger.py's own log_payment_event(), which
# this file never calls (it has always had its own, separate logger).
# ------------------------------------------------------------
_logger = logging.getLogger("rtdn")
if not _logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(_handler)
    _logger.setLevel(logging.INFO)
    _logger.propagate = False


def _log_rtdn_event(
    event: str,
    *,
    correlation_id: str,
    status: str,
    package_name: Optional[str] = None,
    event_type: Optional[str] = None,
    purchase_token: Optional[str] = None,
    action: Optional[str] = None,
    error: Optional[str] = None,
    exc_info: bool = False,
) -> None:
    # S18 -- never let a complete purchase_token reach this log line,
    # whether it's the dedicated field below or embedded inside an
    # exception's own text (e.g. a network-error message that quotes
    # the full Google request URL, which contains the token as a path
    # segment -- the same vector payment_logger.py's callers can hit).
    if error and purchase_token and purchase_token in error:
        error = error.replace(purchase_token, _mask_identifier(purchase_token))

    record = {
        "correlation_id": correlation_id,
        "event": event,
        "status": status,
        "package_name": package_name,
        "event_type": event_type,
        "purchase_token": _mask_identifier(purchase_token),
        "action": action,
        "error": error,
    }
    line = json.dumps(record, default=str)
    if error is not None or exc_info:
        _logger.error(line, exc_info=exc_info)
    else:
        _logger.info(line)


# Google Play RTDN's numeric notificationType -> the string event_type
# SubscriptionService.process_webhook_event() already expects (see
# modules/subscription/subscription_service.py, S7B). Verified against
# Google's own documented enum during the S7A audit.
_RTDN_NOTIFICATION_TYPE_NAMES: Dict[int, str] = {
    1: "SUBSCRIPTION_RECOVERED",
    2: "SUBSCRIPTION_RENEWED",
    3: "SUBSCRIPTION_CANCELED",
    4: "SUBSCRIPTION_PURCHASED",
    5: "SUBSCRIPTION_ON_HOLD",
    6: "SUBSCRIPTION_IN_GRACE_PERIOD",
    7: "SUBSCRIPTION_RESTARTED",
    8: "SUBSCRIPTION_PRICE_CHANGE_CONFIRMED",
    9: "SUBSCRIPTION_DEFERRED",
    10: "SUBSCRIPTION_PAUSED",
    11: "SUBSCRIPTION_PAUSE_SCHEDULE_CHANGED",
    12: "SUBSCRIPTION_REVOKED",
    13: "SUBSCRIPTION_EXPIRED",
    20: "SUBSCRIPTION_PENDING_PURCHASE_CANCELED",
}


class _MalformedRtdnPayload(Exception):
    """Raised internally by the parsing helpers below to short-circuit
    straight to a 400 response with a specific reason -- never
    exposed outside this module."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _decode_pubsub_envelope(raw_body: bytes) -> Dict[str, Any]:
    """Step 1+2 of the flow: parse the Pub/Sub push envelope and
    base64-decode its `message.data` into Google Play's own RTDN JSON
    object. Raises _MalformedRtdnPayload for anything that does not
    parse -- never lets a ValueError/KeyError/etc. escape raw."""
    try:
        envelope = json.loads(raw_body)
    except (ValueError, TypeError):
        raise _MalformedRtdnPayload("request body is not valid JSON")

    if not isinstance(envelope, dict):
        raise _MalformedRtdnPayload("request body is not a JSON object")

    message = envelope.get("message")
    if not isinstance(message, dict):
        raise _MalformedRtdnPayload("envelope is missing a 'message' object")

    data_b64 = message.get("data")
    if not data_b64:
        raise _MalformedRtdnPayload("message.data is missing")

    try:
        decoded_bytes = base64.b64decode(data_b64)
    except (binascii.Error, ValueError):
        raise _MalformedRtdnPayload("message.data is not valid base64")

    try:
        notification = json.loads(decoded_bytes)
    except (ValueError, TypeError, UnicodeDecodeError):
        raise _MalformedRtdnPayload("decoded message.data is not valid JSON")

    if not isinstance(notification, dict):
        raise _MalformedRtdnPayload("decoded message.data is not a JSON object")

    return notification


def _identify_notification(notification: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    """Step 3 of the flow. Returns (event_type, purchase_token).
    purchase_token is None only for TEST_NOTIFICATION, which has none.
    Raises _MalformedRtdnPayload if neither a subscriptionNotification
    nor a testNotification block is present, or if
    subscriptionNotification is missing its purchaseToken."""
    if "testNotification" in notification:
        return "TEST_NOTIFICATION", None

    sub_notification = notification.get("subscriptionNotification")
    if not isinstance(sub_notification, dict):
        raise _MalformedRtdnPayload(
            "notification has neither subscriptionNotification nor testNotification"
        )

    purchase_token = sub_notification.get("purchaseToken")
    if not purchase_token:
        raise _MalformedRtdnPayload("subscriptionNotification is missing purchaseToken")

    notification_type_code = sub_notification.get("notificationType")
    event_type = _RTDN_NOTIFICATION_TYPE_NAMES.get(notification_type_code)
    return event_type, purchase_token


@routes_rtdn.route("/webhooks/google-play/rtdn", methods=["POST"])
def receive_rtdn():
    correlation_id = uuid.uuid4().hex

    # Authentication gate (S7D) -- must run before any parsing. Only a
    # request Google Cloud Pub/Sub itself signed may reach the
    # dispatcher at all; every failure mode here is a structured
    # PubSubAuthResult, never an exception, so this is a plain
    # if-not-authenticated check, not a try/except.
    auth_result = PubSubAuthService().verify_request(request.headers.get("Authorization"))
    if not auth_result.authenticated:
        _log_rtdn_event(
            "rtdn_auth_failed", correlation_id=correlation_id, status=auth_result.status,
            error=auth_result.error_message,
        )
        return jsonify({"error": "unauthorized", "reason": auth_result.status}), 401

    raw_body = request.get_data()

    try:
        notification = _decode_pubsub_envelope(raw_body)
    except _MalformedRtdnPayload as exc:
        _log_rtdn_event(
            "rtdn_received", correlation_id=correlation_id, status="MALFORMED_ENVELOPE",
            error=exc.reason,
        )
        return jsonify({"error": "malformed_payload", "message": exc.reason}), 400

    package_name = notification.get("packageName")

    try:
        event_type, purchase_token = _identify_notification(notification)
    except _MalformedRtdnPayload as exc:
        _log_rtdn_event(
            "rtdn_received", correlation_id=correlation_id, status="MALFORMED_NOTIFICATION",
            package_name=package_name, error=exc.reason,
        )
        return jsonify({"error": "malformed_payload", "message": exc.reason}), 400

    if event_type is None:
        # A real Google notificationType this static mapping does not
        # know about yet (a future enum value). Nothing to dispatch --
        # retrying would not teach this code a new mapping -- ack and
        # log for visibility.
        _log_rtdn_event(
            "rtdn_received", correlation_id=correlation_id, status="UNRECOGNIZED_NOTIFICATION_TYPE",
            package_name=package_name, purchase_token=purchase_token,
        )
        return jsonify({"status": "ignored", "reason": "unrecognized_notification_type"}), 200

    # Identity resolution (S7E) -- RTDN carries no profile_id at all;
    # resolve it from the mapping PaymentService recorded at purchase
    # time. None (unresolved) is a legitimate outcome for a purchase
    # this system genuinely never saw -- the dispatcher's own
    # MISSING_PROFILE_ID reporting (S7B, unmodified) handles that
    # honestly rather than this endpoint guessing.
    resolved_profile_id = (
        SubscriptionPurchaseMappingService().resolve_profile_id(purchase_token)
        if purchase_token else None
    )

    _log_rtdn_event(
        "rtdn_received", correlation_id=correlation_id, status="PARSED",
        package_name=package_name, event_type=event_type, purchase_token=purchase_token,
    )

    payload = {
        "purchase_token": purchase_token,
        "package_name": package_name,
        "profile_id": resolved_profile_id,
    }

    try:
        result = SubscriptionService().process_webhook_event(
            provider="GOOGLE_PLAY", event_type=event_type, payload=payload,
        )
    except Exception as exc:
        # Includes the deliberate NotImplementedError for
        # SUBSCRIPTION_PAUSED/SUBSCRIPTION_RESTARTED (S7B) as well as
        # any genuine infrastructure failure -- both should be retried
        # by Pub/Sub's own backoff, so both get a non-2xx here.
        _log_rtdn_event(
            "rtdn_dispatch_failed", correlation_id=correlation_id, status="EXCEPTION",
            package_name=package_name, event_type=event_type, purchase_token=purchase_token,
            error=str(exc), exc_info=True,
        )
        return jsonify({"error": "dispatch_failed", "message": str(exc)}), 500

    _log_rtdn_event(
        "rtdn_dispatched", correlation_id=correlation_id,
        status="SUCCESS" if result.success else "BUSINESS_FAILURE",
        package_name=package_name, event_type=event_type, purchase_token=purchase_token,
        action=result.action,
    )
    return jsonify({"status": "ok", "action": result.action}), 200
