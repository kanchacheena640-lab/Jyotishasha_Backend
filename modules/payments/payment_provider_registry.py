# modules/payments/payment_provider_registry.py

"""
PaymentProviderRegistry -- resolves a PaymentProviderType to the
PaymentProvider instance that handles it. Mirrors
modules/ai_report_engine/generator_registry.py's exact shape and
purpose: PaymentService depends on this registry, never on a specific
provider class by name, so adding a real GooglePlayProvider/
AppleProvider implementation later never requires touching
PaymentService.
"""

from __future__ import annotations

from typing import Dict, Optional

from modules.payments.apple_provider import AppleProvider
from modules.payments.google_play_provider import GooglePlayProvider
from modules.payments.payment_models import PaymentProviderType
from modules.payments.payment_provider import PaymentProvider
from modules.payments.razorpay_provider import RazorpayProvider


class UnknownPaymentProviderError(Exception):
    pass


class PaymentProviderRegistry:
    def __init__(self):
        self._providers: Dict[str, PaymentProvider] = {}

    def register(self, provider_type: str, provider: PaymentProvider) -> None:
        self._providers[provider_type] = provider

    def resolve(self, provider_type: str) -> PaymentProvider:
        provider = self._providers.get(provider_type)
        if provider is None:
            raise UnknownPaymentProviderError(f"No provider registered for {provider_type!r}")
        return provider

    def as_dict(self) -> Dict[str, PaymentProvider]:
        return dict(self._providers)

    def registered_providers(self):
        return tuple(self._providers.keys())


_default_registry: Optional[PaymentProviderRegistry] = None


def _register_default_providers(registry: PaymentProviderRegistry) -> None:
    registry.register(PaymentProviderType.RAZORPAY, RazorpayProvider())
    registry.register(PaymentProviderType.GOOGLE_PLAY, GooglePlayProvider())
    registry.register(PaymentProviderType.APPLE, AppleProvider())


def get_default_registry() -> PaymentProviderRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = PaymentProviderRegistry()
        _register_default_providers(_default_registry)
    return _default_registry
