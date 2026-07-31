# modules/payments/payment_provider.py

"""
PaymentProvider -- the abstract interface every payment rail
implements. Mirrors modules/ai_report_engine/generator_interface.py's
ReportGenerator role: one small abstract contract, one concrete
implementation per rail, resolved through a registry
(payment_provider_registry.py) rather than PaymentService knowing
about any specific provider by name.

A provider's only job is verification -- turning a PaymentRequest into
a PaymentVerificationResult. Providers never touch Order,
CurrentEntitlement, SubscriptionEvent, or any other business table, and
never generate reports themselves; that separation is enforced by
PaymentService, not by this file, but no provider implementation
should ever need to import OrderService or SubscriptionService to do
its job.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from modules.payments.payment_models import PaymentRequest, PaymentVerificationResult


class PaymentProvider(ABC):
    provider_type: str  # set by each subclass to a PaymentProviderType value

    @abstractmethod
    def verify(self, request: PaymentRequest) -> PaymentVerificationResult:
        """Verify one payment claim and return a structured result.
        Must never raise for an ordinary verification failure (wrong
        signature, unimplemented provider, etc.) -- that's a
        PaymentStatus.FAILED/NOT_IMPLEMENTED result, not an exception.
        An exception here means something infrastructural went wrong
        (e.g. the provider's SDK/network call itself failed), exactly
        the same "structured result vs. real exception" split already
        used by EntitlementWriteService."""
        raise NotImplementedError
