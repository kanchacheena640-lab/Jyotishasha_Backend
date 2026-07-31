# modules/subscription/subscription_state_sync_service.py

"""
SubscriptionStateSyncService -- keeps CurrentEntitlement consistent as
time passes, independent of any purchase/webhook event. This is the
"nothing happened, but time did" side of entitlement: a trial or
subscription that nobody explicitly cancelled or renewed still needs
to be reconciled once its expiry passes.

    Scheduler (cron / Celery / GitHub Actions / any future worker)
        │
        ▼
    SubscriptionStateSyncService
        │
        ├── reads   -> EntitlementService        (current state, read-only)
        └── writes  -> SubscriptionService        (never EntitlementWriteService directly)
                            │
                            ▼
                     EntitlementWriteService (unchanged, still the only writer)
                            │
                            ▼
                     CurrentEntitlement / SubscriptionEvent

This file makes zero changes to CurrentEntitlement, SubscriptionEvent,
EntitlementService, EntitlementWriteService, or SubscriptionService --
all five stay exactly as they already were. Every actual state
transition below is a call to an existing SubscriptionService method
(expire_trial / enter_grace / exit_grace / expire_subscription); this
service decides WHICH one applies by comparing an EntitlementService
snapshot against the current UTC time, and never re-implements any of
EntitlementWriteService's own business rules (one-time trial,
active-subscription protection, etc. all still live there and nowhere
else).

The one place this file reads CurrentEntitlement directly is
sync_all_profiles()'s enumeration query, which lists which profile_ids
currently have a row so it knows what to check -- that is a read-only
SELECT, never a write, and stays clearly marked as such below. Every
actual write, with no exception, goes through SubscriptionService.

Batch strategy: sync_all_profiles() pages through CurrentEntitlement
using keyset pagination (WHERE id > last_seen_id, ordered by id) so an
arbitrarily large table can be swept in fixed-size batches without
loading it all into memory or drifting under OFFSET pagination if rows
change mid-sweep. sync_profiles() is the shared per-batch worker;
sync_all_profiles() is just a loop that keeps calling it.

Error isolation: sync_profile() itself does not catch exceptions -- an
infrastructure failure from EntitlementService/SubscriptionService
propagates exactly as it does everywhere else in this codebase.
sync_profiles()/sync_all_profiles() are the exception: since these are
meant to run unattended over many profiles, a single profile's failure
is caught, recorded in that profile's ProfileSyncOutcome.error, and the
sweep continues -- one bad row should never abort reconciliation for
everyone else. This is a deliberate, narrow exception to this
codebase's "let it propagate" rule, scoped only to the batch loop.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, Optional

from modules.entitlement import EntitlementService, EntitlementWriteResult
from modules.models_premium_subscription import CurrentEntitlement
from modules.subscription.subscription_service import SubscriptionService
from modules.subscription.subscription_state_sync_models import (
    ProfileSyncOutcome,
    SyncBatchResult,
)

# How long a lapsed ACTIVE subscription stays in GRACE before this
# service finalizes it to EXPIRED. Set to 0 to skip grace entirely and
# go straight from ACTIVE to EXPIRED on expiry.
DEFAULT_GRACE_PERIOD_DAYS = 3

DEFAULT_BATCH_SIZE = 500


class SubscriptionStateSyncService:
    def __init__(
        self,
        subscription_service: Optional[SubscriptionService] = None,
        entitlement_service: Optional[EntitlementService] = None,
        grace_period_days: int = DEFAULT_GRACE_PERIOD_DAYS,
    ):
        self._subscription_service = subscription_service or SubscriptionService()
        self._entitlement_service = entitlement_service or EntitlementService()
        self._grace_period_days = grace_period_days

    # ------------------------------------------------------------
    # Single profile
    # ------------------------------------------------------------
    def sync_profile(self, profile_id: int) -> Optional[EntitlementWriteResult]:
        """
        Reconcile ONE profile's entitlement against the current UTC
        time. Returns the EntitlementWriteResult of whichever
        transition was applied, or None if nothing needed to change.
        Does not catch exceptions -- see module docstring.
        """
        snapshot = self._entitlement_service.get_current_entitlement(profile_id)
        now = datetime.utcnow()

        # -- Trial expiry --
        if snapshot.status == "TRIAL":
            if snapshot.trial.expires_at is not None and now >= snapshot.trial.expires_at:
                return self._subscription_service.expire_trial(profile_id)
            return None

        # -- Subscription expiry -> grace entry (if configured), or
        #    straight to expired if grace_period_days == 0 --
        if snapshot.status == "ACTIVE":
            if snapshot.subscription.expires_at is not None and now >= snapshot.subscription.expires_at:
                if self._grace_period_days > 0:
                    return self._subscription_service.enter_grace(profile_id)
                return self._subscription_service.expire_subscription(profile_id)
            return None

        # -- Grace period exit -> expired ("expired entitlement
        #    cleanup" for a lapsed grace window) --
        if snapshot.status == "GRACE":
            if snapshot.subscription.expires_at is not None:
                grace_deadline = snapshot.subscription.expires_at + timedelta(
                    days=self._grace_period_days
                )
                if now >= grace_deadline:
                    return self._subscription_service.exit_grace(profile_id)
            return None

        # PENDING / EXPIRED / CANCELLED / REFUNDED are all terminal or
        # inactive states with nothing time-based left to reconcile --
        # CurrentEntitlement rows are never deleted (same "cache, not
        # history" principle as everywhere else in this system), so
        # there is no further cleanup step for them here.
        return None

    # ------------------------------------------------------------
    # Many profiles (explicit list)
    # ------------------------------------------------------------
    def sync_profiles(self, profile_ids: Iterable[int]) -> SyncBatchResult:
        outcomes = []
        total_changed = 0
        total_errors = 0

        for profile_id in profile_ids:
            try:
                result = self.sync_profile(profile_id)
            except Exception as exc:
                total_errors += 1
                outcomes.append(
                    ProfileSyncOutcome(profile_id=profile_id, changed=False, error=str(exc))
                )
                continue

            if result is not None:
                total_changed += 1
                outcomes.append(
                    ProfileSyncOutcome(
                        profile_id=profile_id, changed=True,
                        action=result.action, write_result=result,
                    )
                )
            else:
                outcomes.append(ProfileSyncOutcome(profile_id=profile_id, changed=False))

        return SyncBatchResult(
            total_checked=len(outcomes),
            total_changed=total_changed,
            total_errors=total_errors,
            outcomes=outcomes,
        )

    # ------------------------------------------------------------
    # Every profile with a CurrentEntitlement row, paged
    # ------------------------------------------------------------
    def sync_all_profiles(self, batch_size: int = DEFAULT_BATCH_SIZE) -> SyncBatchResult:
        """
        Pages through every profile_id that currently has a
        CurrentEntitlement row, batch_size at a time, calling
        sync_profiles() per page. The enumeration query below is
        READ-ONLY (a plain SELECT with keyset pagination) -- it never
        mutates a row. Every actual state transition still happens
        inside sync_profile() via SubscriptionService.
        """
        all_outcomes = []
        total_changed = 0
        total_errors = 0
        last_id = 0

        while True:
            page = (
                CurrentEntitlement.query.with_entities(
                    CurrentEntitlement.id, CurrentEntitlement.profile_id,
                )
                .filter(CurrentEntitlement.id > last_id)
                .order_by(CurrentEntitlement.id.asc())
                .limit(batch_size)
                .all()
            )
            if not page:
                break

            profile_ids = [row.profile_id for row in page]
            batch_result = self.sync_profiles(profile_ids)

            all_outcomes.extend(batch_result.outcomes)
            total_changed += batch_result.total_changed
            total_errors += batch_result.total_errors
            last_id = page[-1].id

        return SyncBatchResult(
            total_checked=len(all_outcomes),
            total_changed=total_changed,
            total_errors=total_errors,
            outcomes=all_outcomes,
        )
