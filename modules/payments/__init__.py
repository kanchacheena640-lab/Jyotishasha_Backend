# modules/payments/__init__.py

"""
modules/payments/ -- Payment Architecture, Phase 1.

Public surface:
    PaymentService           -- the single orchestration layer (verify -> route -> delegate)
    PaymentProviderRegistry  -- resolves PaymentProviderType -> PaymentProvider
    get_default_registry()   -- lazy singleton, pre-registered with Razorpay (real)
                                 + Google Play/Apple (clean placeholders)
    PaymentRequest, PaymentVerificationResult,
    PaymentProviderType, PaymentStatus, PaymentPurpose
    OrderService, CreatedReportOrder

Nothing in this package is wired into any existing route yet -- see
this phase's output notes for Phase 2 TODOs. Every file here is new;
no existing file was modified to add this package.
"""

from modules.payments.order_service import CreatedReportOrder, OrderService
from modules.payments.payment_models import (
    PaymentProviderType,
    PaymentPurpose,
    PaymentRequest,
    PaymentStatus,
    PaymentVerificationResult,
)
from modules.payments.payment_provider import PaymentProvider
from modules.payments.payment_provider_registry import (
    PaymentProviderRegistry,
    UnknownPaymentProviderError,
    get_default_registry,
)
from modules.payments.payment_service import PaymentService
from modules.payments.reconciliation_models import (
    ReconciliationAction,
    ReconciliationDecision,
    ReconciliationResumeResult,
)
from modules.payments.reconciliation_service import ReconciliationService
from modules.payments.metrics_models import (
    GeneralMetrics,
    MetricsLimitation,
    PaymentMetrics,
    PaymentSystemMetricsSnapshot,
    ReportMetrics,
    RetryMetrics,
)
from modules.payments.metrics_service import MetricsService
from modules.payments.google_play_models import (
    GooglePlayAcknowledgementResult,
    GooglePlayAcknowledgementStatus,
    GooglePlaySubscriptionVerification,
    GooglePlayVerificationStatus,
)
from modules.payments.google_play_provider import GooglePlayProvider
from modules.payments.subscription_purchase_models import (
    SubscriptionPurchaseOutcome,
    SubscriptionPurchaseResult,
)
from modules.payments.processed_subscription_event_service import (
    ProcessedSubscriptionEventService,
    SubscriptionEventClaimOutcome,
    SubscriptionEventClaimResult,
)
from modules.payments.pubsub_auth_models import PubSubAuthResult, PubSubAuthStatus
from modules.payments.pubsub_auth_service import PubSubAuthService
from modules.payments.subscription_purchase_mapping_service import (
    SubscriptionPurchaseMappingService,
)

__all__ = [
    "PaymentProviderType",
    "PaymentPurpose",
    "PaymentRequest",
    "PaymentStatus",
    "PaymentVerificationResult",
    "PaymentProvider",
    "PaymentProviderRegistry",
    "UnknownPaymentProviderError",
    "get_default_registry",
    "OrderService",
    "CreatedReportOrder",
    "PaymentService",
    "ReconciliationAction",
    "ReconciliationDecision",
    "ReconciliationResumeResult",
    "ReconciliationService",
    "GeneralMetrics",
    "MetricsLimitation",
    "PaymentMetrics",
    "PaymentSystemMetricsSnapshot",
    "ReportMetrics",
    "RetryMetrics",
    "MetricsService",
    "GooglePlaySubscriptionVerification",
    "GooglePlayVerificationStatus",
    "GooglePlayAcknowledgementResult",
    "GooglePlayAcknowledgementStatus",
    "GooglePlayProvider",
    "SubscriptionPurchaseOutcome",
    "SubscriptionPurchaseResult",
    "ProcessedSubscriptionEventService",
    "SubscriptionEventClaimOutcome",
    "SubscriptionEventClaimResult",
    "PubSubAuthResult",
    "PubSubAuthStatus",
    "PubSubAuthService",
    "SubscriptionPurchaseMappingService",
]
