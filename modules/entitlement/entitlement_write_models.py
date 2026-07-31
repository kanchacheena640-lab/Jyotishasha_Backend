# modules/entitlement/entitlement_write_models.py

"""
Structured return type for EntitlementWriteService. Every public method
on that service returns one of these -- never a raw CurrentEntitlement/
SubscriptionEvent model -- so callers (a future billing webhook, an
admin action, a scheduled grace/expiry sweep) never need to know the
ORM shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class EntitlementWriteResult:
    success: bool
    action: str
    profile_id: int
    previous_status: Optional[str] = None
    new_status: Optional[str] = None
    plan: Optional[str] = None
    selected_segment: Optional[str] = None
    expires_at: Optional[datetime] = None
    message: str = ""
