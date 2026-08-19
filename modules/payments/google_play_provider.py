# modules/payments/google_play_provider.py

"""
GooglePlayProvider -- Subscription Purchase System, Phases S3 and S6.

S6 adds acknowledge_subscription(), the only other real Google Play
API call this class makes. Same contract as verify_subscription_
purchase(): grants nothing, activates nothing, never calls
SubscriptionService/EntitlementWriteService, never touches a database,
never raises a provider exception to its caller. It reuses verify_
subscription_purchase() itself as a pre-check, rather than duplicating
purchase_state/acknowledgement_state parsing a second time -- see
acknowledge_subscription()'s own docstring for why.

Implements REAL verification against the Google Play Developer API
(purchases.subscriptionsv2.get), replacing the clean NOT_IMPLEMENTED
placeholder from Payment Architecture Phase 1. Scope is deliberately
narrow, per this phase's own instructions:

    - Verify a purchase token against Google's own record of it.
    - Return normalized, structured data.
    - Grant nothing. Activate nothing. Write nothing to any database
      table. Never call SubscriptionService/EntitlementWriteService --
      this file does not import either.

verify_subscription_purchase() is the real entry point future phases
(entitlement activation, RTDN handling -- neither implemented here)
will call directly for the rich, normalized result. verify() exists
only to satisfy the PaymentProvider abstract interface PaymentService
already depends on; it delegates to verify_subscription_purchase() and
reshapes the result into the generic PaymentVerificationResult shape,
carrying the full normalized data through in raw_payload -- exactly
the pattern raw_payload was already designed for elsewhere in this
package. PaymentService itself is not modified by this file.

Why this provider catches more than RazorpayProvider does: Razorpay's
checkout-signature check (razorpay_provider.py) is a local HMAC
computation with no network call at all, so an unexpected exception
there really would mean something is infrastructurally wrong, worth
letting propagate per PaymentProvider's own documented contract.
Google Play verification is fundamentally a remote API call --
network failures are a normal, expected, frequent occurrence for it,
not an exceptional one. Every failure mode below (invalid token,
missing/rejected credentials, network failure, anything
unclassified) is therefore caught and returned as a structured
GooglePlaySubscriptionVerification instead of raised, so a caller
never has to know Google's or requests' specific exception types to
handle this provider safely.

Identity note: `purchase_state` and `acknowledgement_state` below are
Google's own raw strings, passed through completely unchanged -- this
file makes no judgment about what they mean for access. That mapping
belongs to a later, explicitly out-of-scope phase (see the Google Play
Lifecycle design review).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

import requests

from config.google_play_config import (
    GOOGLE_PLAY_PACKAGE_NAME,
    get_android_publisher_session,
    get_init_error,
)
from modules.payments.google_play_models import (
    GooglePlayAcknowledgementResult,
    GooglePlayAcknowledgementStatus,
    GooglePlayProductVerification,
    GooglePlaySubscriptionVerification,
    GooglePlayVerificationStatus,
)
from modules.payments.payment_logger import _mask_identifier
from modules.payments.payment_models import (
    PaymentProviderType,
    PaymentPurpose,
    PaymentRequest,
    PaymentStatus,
    PaymentVerificationResult,
)
from modules.payments.payment_provider import PaymentProvider

_ANDROID_PUBLISHER_BASE = "https://androidpublisher.googleapis.com/androidpublisher/v3"


def _parse_rfc3339(value: Optional[str]) -> Optional[datetime]:
    """Google's timestamps look like '2023-01-01T00:00:00.000Z'.
    Returns None (never raises) for anything unparseable -- a
    normalized result should degrade gracefully, not crash the whole
    verification over one unexpected timestamp format."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _parse_millis(value: Optional[Any]) -> Optional[datetime]:
    """Google's ProductPurchase.purchaseTimeMillis is a millisecond-epoch
    value (unlike subscriptions' RFC3339 timestamps) -- never raises for
    anything unparseable, same degrade-gracefully contract as
    _parse_rfc3339 above."""
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000)
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def _extract_google_error(body: Dict[str, Any]) -> Dict[str, Optional[Any]]:
    """
    Diagnostic hardening -- 401/403 responses previously discarded
    Google's own response body entirely, collapsing every distinct
    auth-rejection reason (wrong service account, API not enabled,
    missing Play Console permission, disabled key, ...) into one fixed
    string. Render's logs showed only that fixed string, with nothing
    to distinguish *why* Google rejected the request.

    Extracts ONLY the three safe, non-secret fields from Google's
    standard API error envelope:
        {"error": {"code": ..., "status": ..., "message": ...}}
    Nothing else from the response body is ever read or returned here
    -- no token, no credential, no header, no request echo -- even if
    Google's body happened to contain more. A 401/403 error body is
    Google's own diagnostic text about the credential/permission
    problem itself (e.g. "The caller does not have permission",
    "PERMISSION_DENIED"); it does not carry any of this app's secrets.

    Never raises -- missing/malformed/empty input degrades to
    all-None, matching every other parsing helper in this file's own
    "never raise" contract.
    """
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return {"code": None, "status": None, "message": None}
    return {
        "code": error.get("code"),
        "status": error.get("status"),
        "message": error.get("message"),
    }


def _auth_error_message(body: Dict[str, Any], status_code: int) -> str:
    """Shared, consistent 401/403 diagnostic message -- used by all
    three AUTH_ERROR branches below (subscription verify, product
    verify, acknowledge) so Render's logs carry the same safe detail
    regardless of which Google Play API call failed. Built entirely
    from _extract_google_error()'s already-safe fields; see that
    function's own docstring for exactly what can and cannot appear
    here. Takes the already-parsed body (not the raw response) so
    every call site parses the response exactly once, reusing the same
    parsed dict for both this message and raw_response."""
    google_error = _extract_google_error(body)
    base = (
        f"Google Play rejected this app's own service-account credentials "
        f"(HTTP {status_code})."
    )
    if any(google_error.values()):
        base += (
            f" Google error: code={google_error['code']!r} "
            f"status={google_error['status']!r} message={google_error['message']!r}"
        )
    return base


def _safe_exception_text(exc: Exception, purchase_token: str) -> str:
    """S18: both requests URLs below (verify + acknowledge) embed
    purchase_token directly as a path segment, so a connection/timeout
    exception's own string representation commonly echoes the full
    URL back -- meaning the complete token could otherwise reach
    error_message, and from there a log line, even though the
    dedicated purchase_token field elsewhere is already masked. Scrubs
    the one identifier this method actually knows about, using the
    same centralized masking payment_logger.py's own callers use, so
    there is exactly one masking algorithm in this codebase, not two
    that could drift apart. The rest of the exception text (connection
    details, timeout duration, host) is left intact for diagnostics."""
    text = str(exc)
    if purchase_token and purchase_token in text:
        text = text.replace(purchase_token, _mask_identifier(purchase_token))
    return text


class GooglePlayProvider(PaymentProvider):
    provider_type = PaymentProviderType.GOOGLE_PLAY

    # ------------------------------------------------------------
    # Real entry point for this phase -- returns the rich, normalized
    # result. Never grants entitlement, never touches the database.
    # ------------------------------------------------------------
    def verify_subscription_purchase(
        self, *, purchase_token: str, package_name: Optional[str] = None,
    ) -> GooglePlaySubscriptionVerification:
        package_name = package_name or GOOGLE_PLAY_PACKAGE_NAME

        if not purchase_token:
            return GooglePlaySubscriptionVerification(
                verification_status=GooglePlayVerificationStatus.INVALID_TOKEN,
                purchase_token=purchase_token or "",
                package_name=package_name,
                error_message="purchase_token is required.",
            )

        if not package_name:
            return GooglePlaySubscriptionVerification(
                verification_status=GooglePlayVerificationStatus.AUTH_ERROR,
                purchase_token=purchase_token,
                error_message="GOOGLE_PLAY_PACKAGE_NAME is not configured.",
            )

        session = get_android_publisher_session()
        if session is None:
            return GooglePlaySubscriptionVerification(
                verification_status=GooglePlayVerificationStatus.AUTH_ERROR,
                purchase_token=purchase_token,
                package_name=package_name,
                error_message=get_init_error() or "Google Play credentials are not configured.",
            )

        url = (
            f"{_ANDROID_PUBLISHER_BASE}/applications/{package_name}"
            f"/purchases/subscriptionsv2/tokens/{purchase_token}"
        )

        try:
            response = session.get(url, timeout=15)
        except requests.exceptions.RequestException as exc:
            # A real, expected-to-happen-sometimes network failure --
            # structured, never raised. See module docstring for why
            # this provider's contract differs from RazorpayProvider's.
            return GooglePlaySubscriptionVerification(
                verification_status=GooglePlayVerificationStatus.NETWORK_ERROR,
                purchase_token=purchase_token,
                package_name=package_name,
                error_message=(
                    f"Could not reach Google Play Developer API: "
                    f"{_safe_exception_text(exc, purchase_token)}"
                ),
            )
        except Exception as exc:
            return GooglePlaySubscriptionVerification(
                verification_status=GooglePlayVerificationStatus.UNKNOWN_ERROR,
                purchase_token=purchase_token,
                package_name=package_name,
                error_message=(
                    f"Unexpected error calling Google Play Developer API: "
                    f"{_safe_exception_text(exc, purchase_token)}"
                ),
            )

        return self._parse_response(
            purchase_token=purchase_token, package_name=package_name, response=response,
        )

    def _parse_response(
        self, *, purchase_token: str, package_name: str, response: requests.Response,
    ) -> GooglePlaySubscriptionVerification:
        if response.status_code == 404:
            return GooglePlaySubscriptionVerification(
                verification_status=GooglePlayVerificationStatus.NOT_FOUND,
                purchase_token=purchase_token,
                package_name=package_name,
                error_message="Google Play has no record of this purchase token.",
            )
        if response.status_code == 400:
            return GooglePlaySubscriptionVerification(
                verification_status=GooglePlayVerificationStatus.INVALID_TOKEN,
                purchase_token=purchase_token,
                package_name=package_name,
                error_message="Google Play rejected this purchase token as malformed.",
            )
        if response.status_code in (401, 403):
            error_body = self._safe_json(response)
            return GooglePlaySubscriptionVerification(
                verification_status=GooglePlayVerificationStatus.AUTH_ERROR,
                purchase_token=purchase_token,
                package_name=package_name,
                error_message=_auth_error_message(error_body, response.status_code),
                raw_response=_extract_google_error(error_body),
            )
        if response.status_code != 200:
            return GooglePlaySubscriptionVerification(
                verification_status=GooglePlayVerificationStatus.UNKNOWN_ERROR,
                purchase_token=purchase_token,
                package_name=package_name,
                error_message=f"Unexpected HTTP {response.status_code} from Google Play.",
                raw_response=self._safe_json(response),
            )

        body = self._safe_json(response)
        line_items = body.get("lineItems") or []
        first_item: Dict[str, Any] = line_items[0] if line_items else {}
        auto_renewing_plan = first_item.get("autoRenewingPlan") or {}

        return GooglePlaySubscriptionVerification(
            verification_status=GooglePlayVerificationStatus.VERIFIED,
            purchase_token=purchase_token,
            package_name=package_name,
            purchase_state=body.get("subscriptionState"),
            acknowledgement_state=body.get("acknowledgementState"),
            order_id=body.get("latestOrderId"),
            product_id=first_item.get("productId"),
            subscription_id=first_item.get("productId"),
            expiry_time=_parse_rfc3339(first_item.get("expiryTime")),
            start_time=_parse_rfc3339(body.get("startTime")),
            auto_renewing=auto_renewing_plan.get("autoRenewEnabled"),
            country=body.get("regionCode"),
            linked_purchase_token=body.get("linkedPurchaseToken"),
            raw_response=body,
        )

    @staticmethod
    def _safe_json(response: requests.Response) -> Dict[str, Any]:
        try:
            return response.json()
        except ValueError:
            return {}

    # ------------------------------------------------------------
    # Google Play ONE-TIME PRODUCT verification -- the Premium PDF
    # Report counterpart to verify_subscription_purchase() above.
    # Implements REAL verification against the Google Play Developer
    # API (purchases.products.get), the products-namespace sibling of
    # purchases.subscriptionsv2.get -- a one-time consumable purchase
    # token (e.g. "reports51") has no record in the subscriptions
    # namespace at all, which is exactly why verify_subscription_
    # purchase() could never verify one.
    #
    # Same scope discipline as verify_subscription_purchase(): verify a
    # purchase token against Google's own record of it, return
    # normalized structured data, grant nothing, write nothing to any
    # database table. Never calls OrderService/PaymentService itself --
    # this file does not import either.
    #
    # Reuses everything verify_subscription_purchase() already reuses:
    # the same get_android_publisher_session() credentials/session, the
    # same GOOGLE_PLAY_PACKAGE_NAME config, the same "never raise, always
    # return a structured GooglePlayVerificationStatus" error contract,
    # and the same _safe_exception_text() masking for logging.
    # ------------------------------------------------------------
    def verify_product_purchase(
        self, *, purchase_token: str, product_id: str, package_name: Optional[str] = None,
    ) -> GooglePlayProductVerification:
        package_name = package_name or GOOGLE_PLAY_PACKAGE_NAME

        if not purchase_token:
            return GooglePlayProductVerification(
                verification_status=GooglePlayVerificationStatus.INVALID_TOKEN,
                purchase_token=purchase_token or "",
                product_id=product_id,
                package_name=package_name,
                error_message="purchase_token is required.",
            )

        if not product_id:
            return GooglePlayProductVerification(
                verification_status=GooglePlayVerificationStatus.INVALID_TOKEN,
                purchase_token=purchase_token,
                product_id=product_id,
                package_name=package_name,
                error_message="product_id is required.",
            )

        if not package_name:
            return GooglePlayProductVerification(
                verification_status=GooglePlayVerificationStatus.AUTH_ERROR,
                purchase_token=purchase_token,
                product_id=product_id,
                error_message="GOOGLE_PLAY_PACKAGE_NAME is not configured.",
            )

        session = get_android_publisher_session()
        if session is None:
            return GooglePlayProductVerification(
                verification_status=GooglePlayVerificationStatus.AUTH_ERROR,
                purchase_token=purchase_token,
                product_id=product_id,
                package_name=package_name,
                error_message=get_init_error() or "Google Play credentials are not configured.",
            )

        url = (
            f"{_ANDROID_PUBLISHER_BASE}/applications/{package_name}"
            f"/purchases/products/{product_id}/tokens/{purchase_token}"
        )

        try:
            response = session.get(url, timeout=15)
        except requests.exceptions.RequestException as exc:
            # A real, expected-to-happen-sometimes network failure --
            # structured, never raised. Same contract as
            # verify_subscription_purchase() above.
            return GooglePlayProductVerification(
                verification_status=GooglePlayVerificationStatus.NETWORK_ERROR,
                purchase_token=purchase_token,
                product_id=product_id,
                package_name=package_name,
                error_message=(
                    f"Could not reach Google Play Developer API: "
                    f"{_safe_exception_text(exc, purchase_token)}"
                ),
            )
        except Exception as exc:
            return GooglePlayProductVerification(
                verification_status=GooglePlayVerificationStatus.UNKNOWN_ERROR,
                purchase_token=purchase_token,
                product_id=product_id,
                package_name=package_name,
                error_message=(
                    f"Unexpected error calling Google Play Developer API: "
                    f"{_safe_exception_text(exc, purchase_token)}"
                ),
            )

        return self._parse_product_response(
            purchase_token=purchase_token, product_id=product_id,
            package_name=package_name, response=response,
        )

    def _parse_product_response(
        self, *, purchase_token: str, product_id: str, package_name: str, response: requests.Response,
    ) -> GooglePlayProductVerification:
        if response.status_code == 404:
            return GooglePlayProductVerification(
                verification_status=GooglePlayVerificationStatus.NOT_FOUND,
                purchase_token=purchase_token,
                product_id=product_id,
                package_name=package_name,
                error_message="Google Play has no record of this purchase token.",
            )
        if response.status_code == 400:
            return GooglePlayProductVerification(
                verification_status=GooglePlayVerificationStatus.INVALID_TOKEN,
                purchase_token=purchase_token,
                product_id=product_id,
                package_name=package_name,
                error_message="Google Play rejected this purchase token as malformed.",
            )
        if response.status_code in (401, 403):
            error_body = self._safe_json(response)
            return GooglePlayProductVerification(
                verification_status=GooglePlayVerificationStatus.AUTH_ERROR,
                purchase_token=purchase_token,
                product_id=product_id,
                package_name=package_name,
                error_message=_auth_error_message(error_body, response.status_code),
                raw_response=_extract_google_error(error_body),
            )
        if response.status_code != 200:
            return GooglePlayProductVerification(
                verification_status=GooglePlayVerificationStatus.UNKNOWN_ERROR,
                purchase_token=purchase_token,
                product_id=product_id,
                package_name=package_name,
                error_message=f"Unexpected HTTP {response.status_code} from Google Play.",
                raw_response=self._safe_json(response),
            )

        body = self._safe_json(response)

        return GooglePlayProductVerification(
            verification_status=GooglePlayVerificationStatus.VERIFIED,
            purchase_token=purchase_token,
            product_id=product_id,
            package_name=package_name,
            purchase_state=body.get("purchaseState"),
            consumption_state=body.get("consumptionState"),
            acknowledgement_state=body.get("acknowledgementState"),
            order_id=body.get("orderId"),
            purchase_time=_parse_millis(body.get("purchaseTimeMillis")),
            country=body.get("regionCode"),
            raw_response=body,
        )

    # ------------------------------------------------------------
    # Subscription Purchase System -- S6. Acknowledgement ONLY: never
    # activates a subscription, never calls SubscriptionService/
    # EntitlementWriteService, never touches a database. Reuses
    # verify_subscription_purchase() (S3, unmodified) as its own
    # pre-check, both to obtain subscription_id (required by Google's
    # acknowledge endpoint, never asked of the caller) and to make
    # ALREADY_ACKNOWLEDGED/REVOKED/EXPIRED detectable BEFORE ever
    # attempting the acknowledge call itself, rather than guessing at
    # Google's acknowledge-endpoint error text for these cases.
    # ------------------------------------------------------------
    def acknowledge_subscription(
        self, *, purchase_token: str, package_name: Optional[str] = None,
    ) -> GooglePlayAcknowledgementResult:
        package_name = package_name or GOOGLE_PLAY_PACKAGE_NAME

        verification = self.verify_subscription_purchase(
            purchase_token=purchase_token, package_name=package_name,
        )

        if verification.verification_status != GooglePlayVerificationStatus.VERIFIED:
            return GooglePlayAcknowledgementResult(
                status=self._map_verification_failure(verification.verification_status),
                purchase_token=purchase_token,
                error_message=verification.error_message,
            )

        if verification.acknowledgement_state == "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED":
            return GooglePlayAcknowledgementResult(
                status=GooglePlayAcknowledgementStatus.ALREADY_ACKNOWLEDGED,
                purchase_token=purchase_token,
                purchase_state=verification.purchase_state,
            )

        if verification.purchase_state == "SUBSCRIPTION_STATE_REVOKED":
            return GooglePlayAcknowledgementResult(
                status=GooglePlayAcknowledgementStatus.REVOKED,
                purchase_token=purchase_token,
                purchase_state=verification.purchase_state,
                error_message="Purchase has been revoked; acknowledgement not attempted.",
            )

        if verification.purchase_state == "SUBSCRIPTION_STATE_EXPIRED":
            return GooglePlayAcknowledgementResult(
                status=GooglePlayAcknowledgementStatus.EXPIRED,
                purchase_token=purchase_token,
                purchase_state=verification.purchase_state,
                error_message="Purchase has expired; acknowledgement not attempted.",
            )

        subscription_id = verification.subscription_id or verification.product_id
        if not subscription_id:
            return GooglePlayAcknowledgementResult(
                status=GooglePlayAcknowledgementStatus.UNKNOWN_ERROR,
                purchase_token=purchase_token,
                purchase_state=verification.purchase_state,
                error_message="Google Play did not provide a product/subscription id to acknowledge against.",
            )

        session = get_android_publisher_session()
        if session is None:
            return GooglePlayAcknowledgementResult(
                status=GooglePlayAcknowledgementStatus.AUTH_ERROR,
                purchase_token=purchase_token,
                purchase_state=verification.purchase_state,
                error_message=get_init_error() or "Google Play credentials are not configured.",
            )

        url = (
            f"{_ANDROID_PUBLISHER_BASE}/applications/{package_name}"
            f"/purchases/subscriptions/{subscription_id}/tokens/{purchase_token}:acknowledge"
        )

        try:
            response = session.post(url, json={}, timeout=15)
        except requests.exceptions.RequestException as exc:
            return GooglePlayAcknowledgementResult(
                status=GooglePlayAcknowledgementStatus.NETWORK_ERROR,
                purchase_token=purchase_token,
                purchase_state=verification.purchase_state,
                error_message=(
                    f"Could not reach Google Play Developer API: "
                    f"{_safe_exception_text(exc, purchase_token)}"
                ),
            )
        except Exception as exc:
            return GooglePlayAcknowledgementResult(
                status=GooglePlayAcknowledgementStatus.UNKNOWN_ERROR,
                purchase_token=purchase_token,
                purchase_state=verification.purchase_state,
                error_message=(
                    f"Unexpected error calling Google Play Developer API: "
                    f"{_safe_exception_text(exc, purchase_token)}"
                ),
            )

        return self._parse_acknowledge_response(
            purchase_token=purchase_token,
            purchase_state=verification.purchase_state,
            response=response,
        )

    def _parse_acknowledge_response(
        self, *, purchase_token: str, purchase_state: Optional[str], response: requests.Response,
    ) -> GooglePlayAcknowledgementResult:
        # Google returns an empty body on success.
        if response.status_code in (200, 204):
            return GooglePlayAcknowledgementResult(
                status=GooglePlayAcknowledgementStatus.ACKNOWLEDGED,
                purchase_token=purchase_token,
                purchase_state=purchase_state,
            )

        body = self._safe_json(response)
        error_message = (body.get("error") or {}).get("message", "") if isinstance(body, dict) else ""

        # Retry-safety net: even with the pre-check above, a concurrent
        # acknowledge from elsewhere could win the race in between --
        # Google's own error for this case is a 400 whose message says
        # so, not a distinct status code. Treated as success, not
        # failure, for the same reason ALREADY_ACKNOWLEDGED is above.
        if response.status_code == 400 and "already" in error_message.lower():
            return GooglePlayAcknowledgementResult(
                status=GooglePlayAcknowledgementStatus.ALREADY_ACKNOWLEDGED,
                purchase_token=purchase_token,
                purchase_state=purchase_state,
                error_message=error_message,
            )
        if response.status_code == 404:
            return GooglePlayAcknowledgementResult(
                status=GooglePlayAcknowledgementStatus.NOT_FOUND,
                purchase_token=purchase_token,
                purchase_state=purchase_state,
                error_message="Google Play has no record of this purchase token.",
            )
        if response.status_code == 400:
            return GooglePlayAcknowledgementResult(
                status=GooglePlayAcknowledgementStatus.INVALID_TOKEN,
                purchase_token=purchase_token,
                purchase_state=purchase_state,
                error_message=error_message or "Google Play rejected this purchase token as malformed.",
            )
        if response.status_code in (401, 403):
            return GooglePlayAcknowledgementResult(
                status=GooglePlayAcknowledgementStatus.AUTH_ERROR,
                purchase_token=purchase_token,
                purchase_state=purchase_state,
                error_message=_auth_error_message(body, response.status_code),
                raw_response=_extract_google_error(body),
            )
        return GooglePlayAcknowledgementResult(
            status=GooglePlayAcknowledgementStatus.UNKNOWN_ERROR,
            purchase_token=purchase_token,
            purchase_state=purchase_state,
            error_message=error_message or f"Unexpected HTTP {response.status_code} from Google Play.",
            raw_response=body if isinstance(body, dict) else {},
        )

    @staticmethod
    def _map_verification_failure(verification_status: str) -> str:
        """The pre-check's verification_status and this method's own
        acknowledgement status are two different enums that happen to
        share several names -- this is the one, explicit place that
        maps one onto the other, rather than assuming the string
        values always coincide."""
        return {
            GooglePlayVerificationStatus.INVALID_TOKEN: GooglePlayAcknowledgementStatus.INVALID_TOKEN,
            GooglePlayVerificationStatus.NOT_FOUND: GooglePlayAcknowledgementStatus.NOT_FOUND,
            GooglePlayVerificationStatus.AUTH_ERROR: GooglePlayAcknowledgementStatus.AUTH_ERROR,
            GooglePlayVerificationStatus.NETWORK_ERROR: GooglePlayAcknowledgementStatus.NETWORK_ERROR,
        }.get(verification_status, GooglePlayAcknowledgementStatus.UNKNOWN_ERROR)

    # ------------------------------------------------------------
    # PaymentProvider interface -- required so PaymentService's
    # existing provider registry can resolve GOOGLE_PLAY at all.
    # PaymentService itself is unmodified; this only fills in the
    # method the abstract base class already requires.
    #
    # Branches on request.purpose -- exactly the field PaymentRequest
    # already carried before this change, per PaymentProviderRegistry
    # resolving by provider type only (one GooglePlayProvider instance
    # for both purposes, not a second provider). The SUBSCRIPTION branch
    # below is byte-for-byte what this method already did; only the new
    # REPORT_PURCHASE branch is added alongside it.
    # ------------------------------------------------------------
    def verify(self, request: PaymentRequest) -> PaymentVerificationResult:
        purchase_token = request.payment_id
        package_name = (request.metadata or {}).get("package_name")

        if request.purpose == PaymentPurpose.REPORT_PURCHASE:
            return self._verify_report_purchase(request, purchase_token, package_name)

        result = self.verify_subscription_purchase(
            purchase_token=purchase_token, package_name=package_name,
        )
        verified = result.verification_status == GooglePlayVerificationStatus.VERIFIED

        return PaymentVerificationResult(
            status=PaymentStatus.VERIFIED if verified else PaymentStatus.FAILED,
            provider=self.provider_type,
            reference=request.reference or result.order_id or "",
            verified=verified,
            message=result.error_message or f"Google Play verification: {result.verification_status}",
            raw_payload=result.to_dict(),
        )

    # Google Play purchaseState values (raw ints from ProductPurchase)
    # that represent a genuinely completed, paid purchase -- see the
    # module-level note in google_play_models.py: 0=Purchased,
    # 1=Canceled, 2=Pending.
    _PRODUCT_PURCHASED_STATE = 0

    def _verify_report_purchase(
        self, request: PaymentRequest, purchase_token: Optional[str], package_name: Optional[str],
    ) -> PaymentVerificationResult:
        """
        REPORT_PURCHASE counterpart to the SUBSCRIPTION branch above.
        One deliberate difference from that branch: PaymentService's
        _apply_business_effect() has a purchase_state gate for
        SUBSCRIPTION (_apply_subscription_business_effect only activates
        for _GOOGLE_PLAY_ACTIVATING_STATES) but NONE for REPORT_PURCHASE
        -- OrderService.create_paid_report_order() runs unconditionally
        the moment this method returns PaymentStatus.VERIFIED. So,
        unlike verify_subscription_purchase() (which only confirms "this
        token is real" and leaves state judgment to a later phase),
        VERIFIED here must also require purchaseState == Purchased --
        otherwise a Canceled or still-Pending purchase token would
        trigger real report generation, with no business-layer check
        left to catch it. This judgment stays inside GooglePlayProvider
        (the file this task approved extending), not inside
        PaymentService or OrderService, both left unmodified.
        """
        product_id = (request.metadata or {}).get("product_id")

        result = self.verify_product_purchase(
            purchase_token=purchase_token, product_id=product_id, package_name=package_name,
        )
        verified = (
            result.verification_status == GooglePlayVerificationStatus.VERIFIED
            and result.purchase_state == self._PRODUCT_PURCHASED_STATE
        )

        if result.verification_status == GooglePlayVerificationStatus.VERIFIED and not verified:
            message = f"Google Play purchase is not in a purchased state (purchaseState={result.purchase_state!r})."
        else:
            message = result.error_message or f"Google Play verification: {result.verification_status}"

        return PaymentVerificationResult(
            status=PaymentStatus.VERIFIED if verified else PaymentStatus.FAILED,
            provider=self.provider_type,
            reference=request.reference or result.order_id or "",
            verified=verified,
            message=message,
            raw_payload=result.to_dict(),
        )
