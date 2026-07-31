# modules/entitlement/__init__.py

"""
Entitlement package (Subscription Phase 2 + EntitlementWriteService).

Public surface:
    EntitlementService        -- the ONLY place allowed to determine Premium access (read-only)
    EntitlementSnapshot        -- structured return type
    TrialStatus                -- structured return type
    SubscriptionStatus         -- structured return type

    EntitlementWriteService    -- the ONLY place allowed to write CurrentEntitlement /
                                   create SubscriptionEvent rows
    EntitlementWriteResult     -- structured return type
"""

from modules.entitlement.entitlement_models import (
    EntitlementSnapshot,
    SubscriptionStatus,
    TrialStatus,
)
from modules.entitlement.entitlement_service import EntitlementService
from modules.entitlement.entitlement_write_models import EntitlementWriteResult
from modules.entitlement.entitlement_write_service import EntitlementWriteService

__all__ = [
    "EntitlementService",
    "EntitlementSnapshot",
    "TrialStatus",
    "SubscriptionStatus",
    "EntitlementWriteService",
    "EntitlementWriteResult",
]
