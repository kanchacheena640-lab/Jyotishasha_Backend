# modules/entitlement/entitlement_models.py

"""
Structured return objects for EntitlementService. Callers never see a
raw CurrentEntitlement/SubscriptionEvent model -- only these plain
dataclasses, so the entitlement schema can evolve without changing
every caller's contract (Premium Reports, Ask Quest, Compatibility,
Notifications, ...).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class TrialStatus:
    is_active: bool
    started_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


@dataclass
class SubscriptionStatus:
    is_active: bool
    status: str
    plan: Optional[str] = None
    started_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    auto_renew: Optional[bool] = None


# The one, first-class set of membership states every caller should
# switch on instead of inferring status from `plan` (which is "free"
# for BOTH an active trial and no subscription at all -- the exact
# ambiguity that made the UI show "No Subscription" during an active
# trial). Every subscription-status API response should expose
# `membership_state` as one of these five, never anything else.
MEMBERSHIP_STATES = ("TRIAL", "ACTIVE", "GRACE_PERIOD", "EXPIRED", "NONE")


@dataclass
class EntitlementSnapshot:
    """The full, current entitlement picture for one profile."""

    profile_id: int
    status: str
    plan: Optional[str]
    selected_segment: Optional[str]
    trial: TrialStatus
    subscription: SubscriptionStatus
    # Fully resolved list of segments this profile currently has access
    # to -- already accounts for trial/plan/selected_segment, so callers
    # never need their own plan-access logic.
    accessible_segments: List[str] = field(default_factory=list)

    @property
    def membership_state(self) -> str:
        """
        Single, unambiguous membership state -- see MEMBERSHIP_STATES.
        Computed entirely from fields this snapshot already carries
        (trial.is_active, status); this is a pure reshaping, not a new
        entitlement decision -- EntitlementService.has_access() and
        every other access-control call are completely unaffected by
        this property.

        A profile currently on an active trial is TRIAL, full stop --
        it must never fall through to NONE/EXPIRED just because `plan`
        is "free" while on trial (the bug this property exists to
        eliminate at the source).
        """
        if self.trial.is_active:
            return "TRIAL"
        if self.status == "ACTIVE":
            return "ACTIVE"
        if self.status == "GRACE":
            return "GRACE_PERIOD"
        if self.status in ("EXPIRED", "TRIAL", "CANCELLED", "REFUNDED"):
            # EXPIRED/CANCELLED/REFUNDED: had access, no longer does.
            # status == "TRIAL" here (trial.is_active is False) means
            # the trial window has passed but SubscriptionStateSyncService
            # hasn't reconciled it to EXPIRED yet -- same user-facing
            # meaning either way, so it's classified identically rather
            # than exposing that internal timing gap to callers.
            return "EXPIRED"
        return "NONE"  # PENDING -- never had a trial or subscription

    @property
    def remaining_trial_days(self) -> Optional[int]:
        """
        Whole days left in the trial window -- None whenever
        membership_state isn't "TRIAL" (including an expired/never-
        started trial), so callers never need their own trial-active
        check before reading this. Reuses trial.expires_at, which
        EntitlementService already computes from CurrentEntitlement;
        this only derives a day-count from it, it never recalculates
        the trial window itself.
        """
        if not self.trial.is_active or self.trial.expires_at is None:
            return None
        remaining_seconds = (self.trial.expires_at - datetime.utcnow()).total_seconds()
        return max(0, math.ceil(remaining_seconds / 86400))
