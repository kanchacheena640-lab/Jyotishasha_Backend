# modules/entitlement/entitlement_models.py

"""
Structured return objects for EntitlementService. Callers never see a
raw CurrentEntitlement/SubscriptionEvent model -- only these plain
dataclasses, so the entitlement schema can evolve without changing
every caller's contract (Premium Reports, Ask Quest, Compatibility,
Notifications, ...).
"""

from __future__ import annotations

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
