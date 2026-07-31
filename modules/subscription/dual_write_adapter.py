# modules/subscription/dual_write_adapter.py

"""
Dual-write adapter -- Subscription Migration Phase 1.

TEMPORARY MIGRATION INFRASTRUCTURE. This file exists only for the
duration of the migration from the legacy subscription systems
(System A: modules/subscription/{models,routes,routes_webhook}.py;
System B: modules/services/subscription_service.py) onto the
Entitlement Engine (System C: modules/entitlement/,
modules/subscription/subscription_service.py). It is meant to be
deleted entirely in the migration plan's Phase 4 (dual-write teardown)
-- everything a future engineer needs to remove lives in this one
file, not scattered across the legacy call sites.

Purpose: whenever a legacy system legitimately changes subscription
state (a trial auto-created, a subscription activated), ALSO write the
equivalent change into System C, so that by the time any consumer
route is later cut over (Phase 3), System C already has correct,
current data for it to read. This file does not change what the
legacy systems do -- every call into it happens strictly AFTER the
legacy write has already committed successfully, and every function
here is best-effort: an exception here is caught, logged, and
swallowed, never allowed to affect the legacy request that triggered
it. This mirrors the exact pattern already established by
modules/user_service.py::provision_trial_for_new_profile() for the
same reason.

Identity mapping: System A's Subscription.user_id is a genuine
users.id (JWT account identity). System C's CurrentEntitlement is
keyed on profile_id (app_users.id). These require the join documented
in Phase 0 (docs/subscription_migration/phase0_identity_mapping.md):
    user_id -> users.id -> users.firebase_uid
             -> app_users.firebase_uid -> app_users.id (profile_id)
resolve_profile_id_from_account_user_id() below performs exactly that
join and nothing else -- reusing the identity resolver's own join
logic, not inventing a new one.

System B is different: tracing modules/services/subscription_service.py
shows its own "user_id" is already operationally an AppUser id (its
own get_user_by_id() resolves it via AppUser.query.get(user_id), not
via the users table) -- it appears to be a misnomer inherited from
System A's naming, not a genuine account-scoped id. Its call site
below passes that id straight through as profile_id, without running
it through the account-identity join, since doing so would be
incorrect (translating an id that is already profile-scoped through a
resolver meant for account-scoped ids).

Known, honest limitation (not fixed here -- out of scope for this
phase): neither legacy system's plan names (System A's
"personalized_horoscope"; System B's "monthly"/"yearly"/
"pro_monthly"/"pro_yearly") exist in System C's SUBSCRIPTION_PLANS
(PRIME_MONTHLY / PRIME_YEARLY / PRIME_PLUS_MONTHLY /
PRIME_PLUS_YEARLY). EntitlementWriteService.activate_subscription()
correctly rejects an unrecognized plan with a structured
success=False result (never an exception, per its own documented
contract) -- so mirror_subscription_activation() below is still
called for every legitimate paid activation (fulfilling "whenever
subscription state changes, attempt to keep both systems
synchronized"), but will predictably report that result until a
plan-name mapping is defined -- an explicit business/architecture
decision the Migration Plan and Consolidation Review already flagged
as open, not something this phase may decide unilaterally.
mirror_trial_start() has no such gap: "free"/trial has no plan name to
translate, so it mirrors cleanly today.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from modules.auth.models import User
from modules.models_user import AppUser
from modules.subscription.subscription_service import SubscriptionService


def resolve_profile_id_from_account_user_id(user_id) -> Optional[int]:
    """
    System A callers only. user_id here is a genuine users.id (JWT
    identity) -- resolves it to a profile_id via the firebase_uid join
    documented in Phase 0. Returns None (never raises) whenever the
    chain can't be completed: no such User, no firebase_uid on it, or
    no AppUser for that firebase_uid. A None return means "skip the
    mirror for this call" -- it must never be treated as an error the
    caller needs to handle.
    """
    try:
        user = User.query.get(user_id)
        if user is None or not user.firebase_uid:
            return None
        app_user = AppUser.query.filter_by(firebase_uid=user.firebase_uid).first()
        return app_user.id if app_user else None
    except Exception as exc:
        print(f"[DualWrite] profile_id resolution failed for user_id={user_id}: {exc}")
        return None


def mirror_trial_start(profile_id: int) -> None:
    """
    Best-effort mirror of a legacy free-trial auto-create into System
    C. profile_id must already be resolved by the caller. Never raises
    -- SubscriptionService.start_trial() is itself idempotent (a
    profile that has already trialed, in either system, is a
    documented no-op there, not an error), so calling this repeatedly
    for the same profile is always safe.
    """
    try:
        result = SubscriptionService().start_trial(profile_id)
        print(f"[DualWrite] start_trial mirrored for profile_id={profile_id}: {result.action}")
    except Exception as exc:
        print(f"[DualWrite] start_trial mirror failed for profile_id={profile_id}: {exc}")


def mirror_subscription_activation(
    profile_id: int,
    *,
    plan: str,
    expires_at: datetime,
    transaction_reference: Optional[str] = None,
) -> None:
    """
    Best-effort mirror of a legacy paid-subscription activation into
    System C. profile_id must already be resolved (or already be a
    profile_id, per System B's call site) by the caller. See this
    module's docstring for the known plan-name mapping gap -- a
    success=False result here is expected and logged, not an error
    condition this function treats specially.
    """
    try:
        result = SubscriptionService().activate_subscription(
            profile_id=profile_id,
            plan=plan,
            selected_segment=None,
            expires_at=expires_at,
            transaction_reference=transaction_reference,
        )
        if result.success:
            print(f"[DualWrite] activate_subscription mirrored for profile_id={profile_id}: {result.action}")
        else:
            print(
                f"[DualWrite] activate_subscription mirror not applied for "
                f"profile_id={profile_id} (plan={plan!r}): {result.message}"
            )
    except Exception as exc:
        print(f"[DualWrite] activate_subscription mirror failed for profile_id={profile_id}: {exc}")
