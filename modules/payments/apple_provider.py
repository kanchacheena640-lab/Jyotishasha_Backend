# modules/payments/apple_provider.py

"""
AppleProvider -- a clean placeholder, symmetric with
GooglePlayProvider. No App Store Server API integration, no receipt
decoding. iOS is a future gateway per this task's context (not yet
live), so this exists purely to complete the provider shape.
"""

from __future__ import annotations

from modules.payments.payment_models import (
    PaymentProviderType,
    PaymentRequest,
    PaymentStatus,
    PaymentVerificationResult,
)
from modules.payments.payment_provider import PaymentProvider


class AppleProvider(PaymentProvider):
    provider_type = PaymentProviderType.APPLE

    def verify(self, request: PaymentRequest) -> PaymentVerificationResult:
        return PaymentVerificationResult(
            status=PaymentStatus.NOT_IMPLEMENTED,
            provider=self.provider_type,
            reference=request.reference or "",
            verified=False,
            message="Apple StoreKit verification is not implemented yet (future phase).",
        )
