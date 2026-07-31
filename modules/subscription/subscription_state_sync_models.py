# modules/subscription/subscription_state_sync_models.py

"""
Structured return types for SubscriptionStateSyncService. Never a raw
CurrentEntitlement/EntitlementWriteResult list without shape -- callers
(a cron job, a Celery task, a GitHub Actions step) get one object back
describing exactly what happened across the whole run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from modules.entitlement import EntitlementWriteResult


@dataclass
class ProfileSyncOutcome:
    profile_id: int
    changed: bool
    action: Optional[str] = None
    write_result: Optional[EntitlementWriteResult] = None
    error: Optional[str] = None


@dataclass
class SyncBatchResult:
    total_checked: int
    total_changed: int
    total_errors: int
    outcomes: List[ProfileSyncOutcome] = field(default_factory=list)
