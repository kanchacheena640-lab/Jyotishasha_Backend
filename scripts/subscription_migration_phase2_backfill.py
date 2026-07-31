#!/usr/bin/env python
# scripts/subscription_migration_phase2_backfill.py

"""
Subscription Migration -- Phase 2: one-time historical backfill.

TEMPORARY MIGRATION INFRASTRUCTURE, run manually and deliberately, not
on a schedule (this is reconciliation of EXISTING historical rows, not
an ongoing sync -- Phase 1's dual-write adapter already keeps NEW
activity in sync going forward). Safe to re-run any number of times:
idempotency comes entirely from re-reading System C's own current
state before acting, not from a separate bookkeeping table -- there is
no second implementation of "have I processed this" here at all.

What this does, and does not, do
---------------------------------
For every row in the two legacy tables (modules/subscription/models.py
::Subscription -- System A; modules/models_subscription.py::
SubscriptionOrder -- System B), this script:

    1. Resolves the row's identity to a profile_id, using the exact
       same join Phase 1's dual-write adapter already uses (System A:
       modules.subscription.dual_write_adapter.
       resolve_profile_id_from_account_user_id; System B: the row's
       user_id is already a profile_id, per Phase 1's own finding).
    2. Reads that profile's CURRENT entitlement via
       modules.entitlement.EntitlementService.get_current_entitlement()
       -- the existing read API, never a raw CurrentEntitlement query.
    3. Only acts if that profile's entitlement is still "PENDING" (no
       CurrentEntitlement row has EVER been created for it) -- this is
       the entire "never overwrite a newer entitlement" / "skip
       already-synchronized profiles" rule: rather than compare
       timestamps against a legacy record's data (fragile, and this is
       reconciliation of the PAST, not an ongoing authority), if the
       profile has ANY entitlement history already -- TRIAL, ACTIVE,
       GRACE, EXPIRED, CANCELLED, or REFUNDED -- this script treats
       that as conclusive proof it is already synchronized (whether by
       Phase 1's dual-write or a previous run of this very script) and
       skips it, unconditionally. It never compares "is this legacy
       record newer" -- it only ever asks "has this profile ever been
       touched by System C at all."
    4. If acting: calls modules.subscription.subscription_service.
       SubscriptionService.start_trial() (System A's plan == "free")
       or .activate_subscription() (anything else) -- the existing
       workflow layer, which itself only ever delegates to
       EntitlementWriteService, the sole writer of CurrentEntitlement/
       SubscriptionEvent. Nothing in this file ever imports or queries
       CurrentEntitlement/SubscriptionEvent directly.

Known, honest limitation (per this phase's own explicit instruction:
report a missing business mapping, never invent one): every paid
activation found in current data (System A's "personalized_horoscope"
plan; System B's "monthly"/"yearly"/"pro_monthly"/"pro_yearly" plan
types) has no equivalent in System C's SUBSCRIPTION_PLANS
(PRIME_MONTHLY / PRIME_YEARLY / PRIME_PLUS_MONTHLY /
PRIME_PLUS_YEARLY). SubscriptionService.activate_subscription() ->
EntitlementWriteService.activate_subscription() correctly rejects
these with a structured success=False result (never an exception,
never a partial write) -- this script reports that outcome verbatim
per profile (action="UNMAPPED_PLAN") and moves on. It does not rename,
translate, or guess a plan mapping for any row. Trial rows ("free")
have no such gap and backfill cleanly today.

Failure handling: each row is processed inside its own try/except --
one bad record is logged with action="ERROR" and full detail, and the
script continues with every remaining record. Nothing here can abort
the run partway through.

Legacy tables (subscriptions, subscription_orders) are read-only in
this file -- not one INSERT/UPDATE/DELETE is issued against either.
Payment/order history is therefore untouched by construction, not by
extra care taken here.

Usage:
    python scripts/subscription_migration_phase2_backfill.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

sys.path.insert(0, ".")

from factory import create_app  # noqa: E402


@dataclass
class BackfillOutcome:
    source: str            # "system_a" | "system_b"
    source_id: int
    user_id: int
    profile_id: Optional[int]
    action: str
    detail: str


@dataclass
class BackfillReport:
    total_considered: int = 0
    outcomes: List[BackfillOutcome] = field(default_factory=list)

    def count(self, action: str) -> int:
        return sum(1 for o in self.outcomes if o.action == action)


def run_backfill() -> BackfillReport:
    from modules.entitlement import EntitlementService
    from modules.models_premium_subscription import SUBSCRIPTION_PLANS
    from modules.models_subscription import SubscriptionOrder
    from modules.subscription.dual_write_adapter import (
        resolve_profile_id_from_account_user_id,
    )
    from modules.subscription.models import Subscription
    from modules.subscription.subscription_service import SubscriptionService

    entitlement_service = EntitlementService()
    subscription_service = SubscriptionService()
    report = BackfillReport()

    def log(outcome: BackfillOutcome) -> None:
        report.outcomes.append(outcome)
        print(
            f"[Phase2] {outcome.source} id={outcome.source_id} user_id={outcome.user_id} "
            f"profile_id={outcome.profile_id} -> {outcome.action}: {outcome.detail}"
        )

    # ----------------------------------------------------------------
    # System A: modules/subscription/models.py::Subscription
    # ----------------------------------------------------------------
    subscriptions = Subscription.query.order_by(Subscription.id.asc()).all()
    for sub in subscriptions:
        report.total_considered += 1
        try:
            profile_id = resolve_profile_id_from_account_user_id(sub.user_id)
            if profile_id is None:
                log(BackfillOutcome(
                    "system_a", sub.id, sub.user_id, None, "SKIPPED_NO_PROFILE",
                    "no AppUser could be resolved for this user_id via the firebase_uid join",
                ))
                continue

            snapshot = entitlement_service.get_current_entitlement(profile_id)
            if snapshot.status != "PENDING":
                log(BackfillOutcome(
                    "system_a", sub.id, sub.user_id, profile_id, "SKIPPED_ALREADY_SYNCED",
                    f"profile already has entitlement history (status={snapshot.status}); "
                    f"never overwritten",
                ))
                continue

            if sub.plan == "free":
                result = subscription_service.start_trial(profile_id)
                if result.action == "TRIAL_STARTED":
                    log(BackfillOutcome(
                        "system_a", sub.id, sub.user_id, profile_id, "MIGRATED_TRIAL",
                        result.message,
                    ))
                else:
                    log(BackfillOutcome(
                        "system_a", sub.id, sub.user_id, profile_id, "SKIPPED_ALREADY_SYNCED",
                        result.message,
                    ))
                continue

            if sub.plan not in SUBSCRIPTION_PLANS:
                log(BackfillOutcome(
                    "system_a", sub.id, sub.user_id, profile_id, "UNMAPPED_PLAN",
                    f"legacy plan {sub.plan!r} has no System C equivalent -- reported, "
                    f"not guessed; needs a business decision before this row can migrate",
                ))
                continue

            result = subscription_service.activate_subscription(
                profile_id=profile_id, plan=sub.plan, selected_segment=None,
                expires_at=sub.end_at, transaction_reference=None,
            )
            # Entitlement was confirmed PENDING just above, so a
            # success=False result here can only be a genuine
            # validation rejection (e.g. this plan requires a
            # selected_segment, which neither legacy table records at
            # all) -- never "already synced". Reported as its own
            # outcome, not guessed around.
            action = "MIGRATED_SUBSCRIPTION" if result.success else "CANNOT_MIGRATE_MISSING_DATA"
            log(BackfillOutcome("system_a", sub.id, sub.user_id, profile_id, action, result.message))

        except Exception as exc:
            log(BackfillOutcome("system_a", sub.id, sub.user_id, None, "ERROR", str(exc)))

    # ----------------------------------------------------------------
    # System B: modules/models_subscription.py::SubscriptionOrder
    # Only "success" orders represent a real, completed activation --
    # "pending"/other statuses never granted anything, nothing to
    # backfill for them.
    # ----------------------------------------------------------------
    orders = SubscriptionOrder.query.order_by(SubscriptionOrder.id.asc()).all()
    for order in orders:
        report.total_considered += 1
        try:
            if order.status != "success":
                log(BackfillOutcome(
                    "system_b", order.id, order.user_id, None, "SKIPPED_NOT_SUCCESSFUL",
                    f"order status={order.status!r}; no completed activation to backfill",
                ))
                continue

            # System B's user_id is already a profile_id (Phase 1's
            # finding: get_user_by_id() resolves it against AppUser
            # directly) -- no firebase_uid join needed or correct here.
            profile_id = order.user_id

            snapshot = entitlement_service.get_current_entitlement(profile_id)
            if snapshot.status != "PENDING":
                log(BackfillOutcome(
                    "system_b", order.id, order.user_id, profile_id, "SKIPPED_ALREADY_SYNCED",
                    f"profile already has entitlement history (status={snapshot.status}); "
                    f"never overwritten",
                ))
                continue

            if order.plan_type not in SUBSCRIPTION_PLANS:
                log(BackfillOutcome(
                    "system_b", order.id, order.user_id, profile_id, "UNMAPPED_PLAN",
                    f"legacy plan_type {order.plan_type!r} has no System C equivalent -- "
                    f"reported, not guessed; needs a business decision before this row "
                    f"can migrate",
                ))
                continue

            expires_at = order.verified_at or order.created_at or datetime.utcnow()
            if "yearly" in order.plan_type:
                from datetime import timedelta
                expires_at = expires_at + timedelta(days=365)
            else:
                from datetime import timedelta
                expires_at = expires_at + timedelta(days=30)

            result = subscription_service.activate_subscription(
                profile_id=profile_id, plan=order.plan_type, selected_segment=None,
                expires_at=expires_at, transaction_reference=order.payment_id,
            )
            # Same reasoning as the System A site above: entitlement
            # was confirmed PENDING just above, so success=False here
            # is a genuine validation rejection, not "already synced".
            action = "MIGRATED_SUBSCRIPTION" if result.success else "CANNOT_MIGRATE_MISSING_DATA"
            log(BackfillOutcome("system_b", order.id, order.user_id, profile_id, action, result.message))

        except Exception as exc:
            log(BackfillOutcome("system_b", order.id, order.user_id, None, "ERROR", str(exc)))

    return report


def print_summary(report: BackfillReport) -> None:
    actions = sorted({o.action for o in report.outcomes})
    print("\n" + "=" * 70)
    print("PHASE 2 BACKFILL SUMMARY")
    print("=" * 70)
    print(f"Total legacy rows considered: {report.total_considered}")
    for action in actions:
        print(f"  {action}: {report.count(action)}")
    unmapped = [o for o in report.outcomes if o.action == "UNMAPPED_PLAN"]
    if unmapped:
        print(f"\n{len(unmapped)} row(s) need a business decision on plan mapping before "
              f"they can be migrated -- NOT guessed by this script:")
        for o in unmapped:
            print(f"  {o.source} id={o.source_id} profile_id={o.profile_id}: {o.detail}")
    missing_data = [o for o in report.outcomes if o.action == "CANNOT_MIGRATE_MISSING_DATA"]
    if missing_data:
        print(f"\n{len(missing_data)} row(s) map to a recognized plan but are missing data "
              f"neither legacy table records (e.g. a required selected_segment) -- NOT "
              f"guessed by this script:")
        for o in missing_data:
            print(f"  {o.source} id={o.source_id} profile_id={o.profile_id}: {o.detail}")
    errors = [o for o in report.outcomes if o.action == "ERROR"]
    if errors:
        print(f"\n{len(errors)} row(s) failed and were skipped (processing continued for all others):")
        for o in errors:
            print(f"  {o.source} id={o.source_id}: {o.detail}")


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        report = run_backfill()
        print_summary(report)
