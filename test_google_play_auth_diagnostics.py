"""
test_google_play_auth_diagnostics.py
----------------------------------
Focused tests for the 401/403 diagnostic-loss fix in
modules/payments/google_play_provider.py.

Tests the response-PARSING logic directly (GooglePlayProvider's own
_parse_response / _parse_product_response / _parse_acknowledge_response
methods) against a minimal fake response object -- no real HTTP call,
no real Google Play Developer API call, no credentials needed at all.
NO NETWORK CALL IS EVER MADE ANYWHERE IN THIS FILE.

Covers:
  1. 401 safe Google error is captured/loggable.
  2. 403 safe Google error is captured/loggable.
  3. secrets/tokens are never exposed by the diagnostic.
  4. verification still fails on 401/403 (never treated as success).
  5. existing successful (200) verification behavior is unchanged.

Exercises all three AUTH_ERROR branches this task's own instructions
called out: subscription verify, product verify, and acknowledge.
"""

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.payments.google_play_provider import GooglePlayProvider, _extract_google_error  # noqa: E402
from modules.payments.google_play_models import (  # noqa: E402
    GooglePlayAcknowledgementStatus,
    GooglePlayVerificationStatus,
)

passed = 0
failed = 0


def check(label, condition):
    global passed, failed
    if condition:
        print(f"  PASS: {label}")
        passed += 1
    else:
        print(f"  FAIL: {label}")
        failed += 1


class FakeResponse:
    """Minimal stand-in for requests.Response -- only .status_code and
    .json() are ever used by the code under test."""

    def __init__(self, status_code, body=None, raise_on_json=False):
        self.status_code = status_code
        self._body = body
        self._raise_on_json = raise_on_json

    def json(self):
        if self._raise_on_json:
            raise ValueError("invalid json")
        return self._body


# A realistic, real-shaped Google auth-rejection body -- plus a couple of
# deliberately "suspicious" extra top-level keys, to prove the extractor
# reads ONLY error.code/error.status/error.message and nothing else,
# even if something unexpected showed up in the body.
REALISTIC_401_BODY = {
    "error": {
        "code": 401,
        "message": "Request had invalid authentication credentials. "
                    "Expected OAuth 2 access token, login cookie or other "
                    "valid authentication credential.",
        "status": "UNAUTHENTICATED",
    },
    # Deliberately suspicious extras -- must NEVER leak through.
    "access_token": "ya29.super-secret-oauth-token-value",
    "authorization": "Bearer some-secret-value",
}

REALISTIC_403_BODY = {
    "error": {
        "code": 403,
        "message": "The current user has insufficient permissions to "
                    "perform the requested operation.",
        "status": "PERMISSION_DENIED",
    },
}

SECRET_PURCHASE_TOKEN = "gpa-super-secret-purchase-token-abc123xyz-do-not-log"


def main():
    provider = GooglePlayProvider()

    # ==========================================================
    print("=== 1: 401 safe Google error is captured/loggable ===")
    # ==========================================================
    result_sub_401 = provider._parse_response(
        purchase_token=SECRET_PURCHASE_TOKEN,
        package_name="com.jyotishasha.app",
        response=FakeResponse(401, REALISTIC_401_BODY),
    )
    check("1: subscription 401 -> AUTH_ERROR", result_sub_401.verification_status == GooglePlayVerificationStatus.AUTH_ERROR)
    check("1: error_message contains Google's status", "UNAUTHENTICATED" in result_sub_401.error_message)
    check("1: error_message contains Google's code", "401" in result_sub_401.error_message)
    check("1: error_message contains Google's own message text", "invalid authentication credentials" in result_sub_401.error_message)
    check("1: raw_response carries only the safe fields", result_sub_401.raw_response == {"code": 401, "status": "UNAUTHENTICATED", "message": REALISTIC_401_BODY["error"]["message"]})

    result_prod_401 = provider._parse_product_response(
        purchase_token=SECRET_PURCHASE_TOKEN,
        product_id="asknow10q",
        package_name="com.jyotishasha.app",
        response=FakeResponse(401, REALISTIC_401_BODY),
    )
    check("1: product 401 -> AUTH_ERROR", result_prod_401.verification_status == GooglePlayVerificationStatus.AUTH_ERROR)
    check("1: product 401 error_message contains Google's status", "UNAUTHENTICATED" in result_prod_401.error_message)

    result_ack_401 = provider._parse_acknowledge_response(
        purchase_token=SECRET_PURCHASE_TOKEN,
        purchase_state="SUBSCRIPTION_STATE_ACTIVE",
        response=FakeResponse(401, REALISTIC_401_BODY),
    )
    check("1: acknowledge 401 -> AUTH_ERROR", result_ack_401.status == GooglePlayAcknowledgementStatus.AUTH_ERROR)
    check("1: acknowledge 401 error_message contains Google's status", "UNAUTHENTICATED" in result_ack_401.error_message)

    # ==========================================================
    print("\n=== 2: 403 safe Google error is captured/loggable ===")
    # ==========================================================
    result_sub_403 = provider._parse_response(
        purchase_token=SECRET_PURCHASE_TOKEN,
        package_name="com.jyotishasha.app",
        response=FakeResponse(403, REALISTIC_403_BODY),
    )
    check("2: subscription 403 -> AUTH_ERROR", result_sub_403.verification_status == GooglePlayVerificationStatus.AUTH_ERROR)
    check("2: error_message contains PERMISSION_DENIED", "PERMISSION_DENIED" in result_sub_403.error_message)
    check("2: error_message contains 403", "403" in result_sub_403.error_message)
    check("2: error_message contains Google's own message text", "insufficient permissions" in result_sub_403.error_message)

    result_prod_403 = provider._parse_product_response(
        purchase_token=SECRET_PURCHASE_TOKEN,
        product_id="asknow8q",
        package_name="com.jyotishasha.app",
        response=FakeResponse(403, REALISTIC_403_BODY),
    )
    check("2: product 403 -> AUTH_ERROR", result_prod_403.verification_status == GooglePlayVerificationStatus.AUTH_ERROR)
    check("2: product 403 error_message contains PERMISSION_DENIED", "PERMISSION_DENIED" in result_prod_403.error_message)

    result_ack_403 = provider._parse_acknowledge_response(
        purchase_token=SECRET_PURCHASE_TOKEN,
        purchase_state="SUBSCRIPTION_STATE_ACTIVE",
        response=FakeResponse(403, REALISTIC_403_BODY),
    )
    check("2: acknowledge 403 -> AUTH_ERROR", result_ack_403.status == GooglePlayAcknowledgementStatus.AUTH_ERROR)
    check("2: acknowledge 403 error_message contains PERMISSION_DENIED", "PERMISSION_DENIED" in result_ack_403.error_message)

    # ==========================================================
    print("\n=== 3: secrets/tokens are never exposed ===")
    # ==========================================================
    for label, result in [
        ("subscription 401", result_sub_401), ("product 401", result_prod_401), ("acknowledge 401", result_ack_401),
        ("subscription 403", result_sub_403), ("product 403", result_prod_403), ("acknowledge 403", result_ack_403),
    ]:
        check(f"3: {label} error_message never contains the purchase token", SECRET_PURCHASE_TOKEN not in result.error_message)
        check(f"3: {label} error_message never contains the suspicious access_token value", "ya29.super-secret-oauth-token-value" not in result.error_message)
        check(f"3: {label} error_message never contains 'authorization'/'bearer'-style leakage", "Bearer some-secret-value" not in result.error_message)

    extracted = _extract_google_error(REALISTIC_401_BODY)
    check("3: _extract_google_error returns EXACTLY {code, status, message} -- no other keys", set(extracted.keys()) == {"code", "status", "message"})
    check("3: _extract_google_error never surfaces access_token", "access_token" not in extracted and extracted.get("message") != REALISTIC_401_BODY.get("access_token"))
    check("3: _extract_google_error never surfaces authorization", "authorization" not in extracted)

    # Malformed/empty/non-dict bodies must degrade safely, never raise,
    # never leak anything.
    check("3: empty body -> all-None, no crash", _extract_google_error({}) == {"code": None, "status": None, "message": None})
    check("3: non-dict 'error' value -> all-None, no crash", _extract_google_error({"error": "oops"}) == {"code": None, "status": None, "message": None})

    # ==========================================================
    print("\n=== 4: verification still fails on 401/403 (never treated as success) ===")
    # ==========================================================
    check("4: subscription 401 is not VERIFIED", result_sub_401.verification_status != GooglePlayVerificationStatus.VERIFIED)
    check("4: product 403 is not VERIFIED", result_prod_403.verification_status != GooglePlayVerificationStatus.VERIFIED)
    check("4: acknowledge 401 is not ACKNOWLEDGED/ALREADY_ACKNOWLEDGED", result_ack_401.status not in (GooglePlayAcknowledgementStatus.ACKNOWLEDGED, GooglePlayAcknowledgementStatus.ALREADY_ACKNOWLEDGED))

    # ==========================================================
    print("\n=== 5: existing successful (200) verification behavior is unchanged ===")
    # ==========================================================
    subscription_200_body = {
        "subscriptionState": "SUBSCRIPTION_STATE_ACTIVE",
        "acknowledgementState": "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED",
        "latestOrderId": "GPA.1234-5678-9012-34567",
        "regionCode": "IN",
        "startTime": "2026-01-01T00:00:00.000Z",
        "lineItems": [{
            "productId": "premium_monthly",
            "expiryTime": "2026-02-01T00:00:00.000Z",
            "autoRenewingPlan": {"autoRenewEnabled": True},
        }],
    }
    result_sub_200 = provider._parse_response(
        purchase_token="tok-success", package_name="com.jyotishasha.app",
        response=FakeResponse(200, subscription_200_body),
    )
    check("5: subscription 200 -> VERIFIED", result_sub_200.verification_status == GooglePlayVerificationStatus.VERIFIED)
    check("5: subscription 200 purchase_state passed through", result_sub_200.purchase_state == "SUBSCRIPTION_STATE_ACTIVE")
    check("5: subscription 200 order_id passed through", result_sub_200.order_id == "GPA.1234-5678-9012-34567")
    check("5: subscription 200 raw_response is the FULL body (unchanged behavior)", result_sub_200.raw_response == subscription_200_body)

    product_200_body = {
        "purchaseState": 0,
        "consumptionState": 0,
        "acknowledgementState": 0,
        "orderId": "GPA.9999-0000-1111-22222",
        "regionCode": "IN",
    }
    result_prod_200 = provider._parse_product_response(
        purchase_token="tok-success", product_id="asknow10q", package_name="com.jyotishasha.app",
        response=FakeResponse(200, product_200_body),
    )
    check("5: product 200 -> VERIFIED", result_prod_200.verification_status == GooglePlayVerificationStatus.VERIFIED)
    check("5: product 200 purchase_state == 0 (Purchased)", result_prod_200.purchase_state == 0)
    check("5: product 200 order_id passed through", result_prod_200.order_id == "GPA.9999-0000-1111-22222")

    result_ack_200 = provider._parse_acknowledge_response(
        purchase_token="tok-success", purchase_state="SUBSCRIPTION_STATE_ACTIVE",
        response=FakeResponse(204),
    )
    check("5: acknowledge 204 -> ACKNOWLEDGED", result_ack_200.status == GooglePlayAcknowledgementStatus.ACKNOWLEDGED)

    # Unrelated status codes (404/400/generic-unknown) must also be
    # completely unaffected by this change.
    result_sub_404 = provider._parse_response(
        purchase_token="tok-x", package_name="com.jyotishasha.app", response=FakeResponse(404, {}),
    )
    check("5: 404 behavior unchanged -> NOT_FOUND", result_sub_404.verification_status == GooglePlayVerificationStatus.NOT_FOUND)

    result_sub_500 = provider._parse_response(
        purchase_token="tok-x", package_name="com.jyotishasha.app", response=FakeResponse(500, {"oops": True}),
    )
    check("5: 500 (unknown) behavior unchanged -> UNKNOWN_ERROR", result_sub_500.verification_status == GooglePlayVerificationStatus.UNKNOWN_ERROR)
    check("5: 500 raw_response still the full safe-json body (unchanged existing behavior)", result_sub_500.raw_response == {"oops": True})

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
