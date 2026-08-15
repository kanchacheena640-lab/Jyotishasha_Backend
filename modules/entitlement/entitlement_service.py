# modules/entitlement/entitlement_service.py

"""
EntitlementService -- THE single source of truth for Premium access.

Every caller (Premium Reports today; Ask Quest, Compatibility, future
Premium features, and Notifications later) must go through this
service. Nobody else queries CurrentEntitlement/SubscriptionEvent
directly.

Identity rule (permanent, per this project's architecture): Premium
access is evaluated ONLY against `profile_id` (AppUser.id) -- never
against `User`/account identity. This service takes a `profile_id` and
nothing else identity-related.

Legacy system: the older, account-scoped `modules/subscription/models.py
::Subscription` (FK'd to `users.id`) is never read here. This service
uses ONLY the new profile-scoped tables in
modules/models_premium_subscription.py.

This service performs no calculation of trial windows, no payment
verification, and no billing/store integration -- it only reads
whatever CurrentEntitlement state already exists and resolves it into
structured, plan-aware access decisions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from modules.models_ai_reports import AI_REPORT_SEGMENTS
from modules.entitlement.subscription_sections import SUBSCRIPTION_SECTIONS
from modules.models_premium_subscription import CurrentEntitlement
from modules.entitlement.entitlement_models import (
    EntitlementSnapshot,
    SubscriptionStatus,
    TrialStatus,
)
from modules.entitlement.plan_access_policy import resolve_accessible_segments

# Both ACTIVE and GRACE count as "currently paying" for access purposes
# -- grace exists precisely so access isn't cut the instant a renewal
# attempt fails.
_ACTIVE_SUBSCRIPTION_STATUSES = ("ACTIVE", "GRACE")


class EntitlementService:
    # ------------------------------------------------------------
    # Public methods (Phase 2 responsibilities)
    # ------------------------------------------------------------
    def get_current_entitlement(self, profile_id: int) -> EntitlementSnapshot:
        """The full, structured entitlement picture for this profile.
        Every other public method on this service is a thin read of
        this same snapshot."""
        row = CurrentEntitlement.query.filter_by(profile_id=profile_id).first()

        if row is None:
            # No CurrentEntitlement row has ever been created for this
            # profile (no trial started, nothing purchased yet). This
            # service only reads state -- it never creates one itself.
            return EntitlementSnapshot(
                profile_id=profile_id,
                status="PENDING",
                plan=None,
                selected_segment=None,
                trial=TrialStatus(is_active=False),
                subscription=SubscriptionStatus(is_active=False, status="PENDING"),
                accessible_segments=[],
            )

        trial = TrialStatus(
            is_active=self._is_trial_window_active(row),
            started_at=row.trial_started_at,
            expires_at=row.trial_expires_at,
        )

        subscription_is_active = row.status in _ACTIVE_SUBSCRIPTION_STATUSES
        subscription = SubscriptionStatus(
            is_active=subscription_is_active,
            status=row.status,
            plan=row.plan,
            started_at=row.subscription_started_at,
            expires_at=row.subscription_expires_at,
            auto_renew=row.auto_renew,
        )

        if trial.is_active:
            # A trial is a promotional window, not plan-restricted --
            # it grants every SUBSCRIPTION section, including Alerts &
            # Opportunities (the 6th section, added when Alerts became a
            # selectable section -- see
            # modules/entitlement/subscription_sections.py). Deliberately
            # SUBSCRIPTION_SECTIONS, not AI_REPORT_SEGMENTS: a trial
            # grants access to every premium SECTION, not literally every
            # AI-report generator (Alerts has none, by design).
            accessible_segments = list(SUBSCRIPTION_SECTIONS)
        elif subscription_is_active:
            accessible_segments = resolve_accessible_segments(row.plan, row.selected_segment)
        else:
            accessible_segments = []

        return EntitlementSnapshot(
            profile_id=profile_id,
            status=row.status,
            plan=row.plan,
            selected_segment=row.selected_segment,
            trial=trial,
            subscription=subscription,
            accessible_segments=accessible_segments,
        )

    def is_trial_active(self, profile_id: int) -> bool:
        return self.get_current_entitlement(profile_id).trial.is_active

    def is_subscription_active(self, profile_id: int) -> bool:
        return self.get_current_entitlement(profile_id).subscription.is_active

    def has_access(self, profile_id: int, segment: str) -> bool:
        if segment not in AI_REPORT_SEGMENTS:
            raise ValueError(f"Unknown segment: {segment!r}")
        return segment in self.get_current_entitlement(profile_id).accessible_segments

    def get_plan(self, profile_id: int) -> Optional[str]:
        return self.get_current_entitlement(profile_id).plan

    def get_trial_status(self, profile_id: int) -> TrialStatus:
        return self.get_current_entitlement(profile_id).trial

    def get_subscription_status(self, profile_id: int) -> SubscriptionStatus:
        return self.get_current_entitlement(profile_id).subscription

    # ------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------
    def _is_trial_window_active(self, row: CurrentEntitlement) -> bool:
        if row.status != "TRIAL":
            return False
        if row.trial_expires_at is None:
            return False
        return datetime.utcnow() < row.trial_expires_at
