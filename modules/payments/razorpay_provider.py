# modules/payments/razorpay_provider.py

"""
RazorpayProvider -- the one PaymentProvider with a real, working
implementation in Phase 1. Uses the SAME razorpay_client already
configured in config/razorpay_config.py (no new credentials, no new
config) and Razorpay's own SDK-provided HMAC verification
(razorpay.utility.Utility.verify_payment_signature), which this
codebase's existing Razorpay call sites never actually called before
this phase -- every one of them (app.py, modules/subscription/routes.py,
modules/services/subscription_service.py, asknow_service.py,
chat_pack_service.py) trusted a client-supplied order_id/payment_id
with no cryptographic check, per the Payment Consolidation Audit.

Verification method: Razorpay's Checkout.js flow returns
razorpay_order_id, razorpay_payment_id, and razorpay_signature to the
client after a successful payment; the signature is
HMAC-SHA256(order_id + "|" + payment_id, key_secret). This provider
checks exactly that, via the SDK rather than reimplementing the HMAC
itself, so any future SDK-level fix/change is inherited for free.

This file does not create/update any Order, CurrentEntitlement, or
other business row -- it only answers "is this payment claim real."

Server-to-server recovery (Payment Hardening -- Blocker 01): Razorpay
also pushes a `payment.captured` event directly to /webhook, signed a
completely different way -- an HMAC over the ENTIRE raw request body,
using a separate Webhook Secret (never RAZORPAY_KEY_SECRET), delivered
in the X-Razorpay-Signature header. That is a genuinely different
cryptographic check (different algorithm input, different secret), so
it gets its own method, verify_webhook_signature(), rather than being
forced through verify()'s per-payment reference/payment_id/signature
shape, which the server webhook payload never carries at all.

Once app.py has independently confirmed a payment.captured delivery is
authentic via verify_webhook_signature(), it builds the exact same
PaymentRequest shape verify() already handles for the browser path --
just with metadata={"source": "webhook"} instead of a checkout
signature. verify() below treats that as proof already established
(the request-level HMAC already IS the verification for that delivery
mechanism) rather than demanding a checkout signature that a
server-to-server event will never have. This is what lets both entry
points converge on the one call PaymentService.process_payment()
already makes to provider.verify(request) -- no second verification
path, no change to PaymentService itself.
"""

from __future__ import annotations

from razorpay.errors import SignatureVerificationError

from config.razorpay_config import RAZORPAY_WEBHOOK_SECRET, razorpay_client
from modules.payments.payment_models import (
    PaymentProviderType,
    PaymentRequest,
    PaymentStatus,
    PaymentVerificationResult,
)
from modules.payments.payment_provider import PaymentProvider


class RazorpayProvider(PaymentProvider):
    provider_type = PaymentProviderType.RAZORPAY

    def verify(self, request: PaymentRequest) -> PaymentVerificationResult:
        if not request.reference or not request.payment_id:
            return PaymentVerificationResult(
                status=PaymentStatus.FAILED,
                provider=self.provider_type,
                reference=request.reference or "",
                verified=False,
                message="Razorpay verification requires reference (order_id) "
                        "and payment_id -- one or both was missing.",
            )

        if request.metadata.get("source") == "webhook":
            # Authenticity for this request was already established by
            # app.py calling verify_webhook_signature() against the raw
            # request body before this PaymentRequest was ever built --
            # there is no checkout-style signature to check here (a
            # server webhook payload never contains one), so re-demanding
            # one would be wrong, not just redundant.
            return PaymentVerificationResult(
                status=PaymentStatus.VERIFIED,
                provider=self.provider_type,
                reference=request.reference,
                verified=True,
                message="Razorpay payment.captured webhook signature verified.",
            )

        if not request.signature:
            return PaymentVerificationResult(
                status=PaymentStatus.FAILED,
                provider=self.provider_type,
                reference=request.reference,
                verified=False,
                message="Razorpay verification requires a signature for a "
                        "browser-originated request.",
            )

        params = {
            "razorpay_order_id": request.reference,
            "razorpay_payment_id": request.payment_id,
            "razorpay_signature": request.signature,
        }

        try:
            razorpay_client.utility.verify_payment_signature(params)
        except SignatureVerificationError as exc:
            return PaymentVerificationResult(
                status=PaymentStatus.FAILED,
                provider=self.provider_type,
                reference=request.reference,
                verified=False,
                message=f"Razorpay signature verification failed: {exc}",
            )

        return PaymentVerificationResult(
            status=PaymentStatus.VERIFIED,
            provider=self.provider_type,
            reference=request.reference,
            verified=True,
            message="Razorpay signature verified.",
        )

    @staticmethod
    def verify_webhook_signature(raw_body: str, signature: str) -> bool:
        """
        Authenticates a server-to-server webhook delivery: HMAC-SHA256
        over the entire raw request body, keyed by the Webhook Secret
        (RAZORPAY_WEBHOOK_SECRET) -- not the checkout signature check
        verify() performs above, and not RAZORPAY_KEY_SECRET. raw_body
        must be the exact, unmodified request body text Razorpay signed
        (request.get_data(as_text=True) in app.py) -- re-serializing the
        parsed JSON would very likely change byte-for-byte content
        (key order, whitespace) and break the HMAC.

        Returns False for "not authentic" (bad signature) or "cannot
        verify" (no webhook secret configured) alike -- app.py must
        treat both identically: never process an unverified delivery.
        """
        if not signature or not RAZORPAY_WEBHOOK_SECRET:
            return False
        try:
            return razorpay_client.utility.verify_webhook_signature(
                raw_body, signature, RAZORPAY_WEBHOOK_SECRET,
            )
        except SignatureVerificationError:
            return False
