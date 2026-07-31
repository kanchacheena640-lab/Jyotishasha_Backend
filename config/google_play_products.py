# config/google_play_products.py

"""
Centralized Google Play Console product configuration (Subscription
Purchase System -- S11). Single source of truth for every real Play
Console subscription product this app sells -- production
configuration, finalized.

GOOGLE_PLAY_PRODUCT_TO_PLAN (the flat product_id -> plan name dict
PaymentService's _apply_subscription_business_effect() and the RTDN
dispatcher's _dispatch_verified_event() -- modules/payments/
payment_service.py and modules/subscription/subscription_service.py,
both unmodified by this phase -- already consume via
.get(product_id)) is derived from GOOGLE_PLAY_PRODUCTS below, never
maintained separately. There is exactly one place this mapping is
defined; nothing is hardcoded inside PaymentService itself.

base_plan_id is documentation/reference metadata only -- it is NOT
used to gate plan resolution, and nothing in this codebase currently
reads it at runtime. Plan identity is keyed on product_id alone,
matching how the RTDN dispatcher already resolves a purchase's plan
(unmodified, per this phase's own constraints): a product_id is never
reused across two different plans, so product_id alone is sufficient
and correct. A base plan change within one product (e.g. Gold's
original "monthly" base plan going inactive, replaced by "monthlyc")
is Google's own pricing/offer versioning inside a single product --
it does not change which internal plan that product activates.

An unknown product_id -- anything not a key below -- correctly falls
through GOOGLE_PLAY_PRODUCT_TO_PLAN.get(product_id) to None, and
PaymentService already reports that as UNMAPPED_PRODUCT rather than
guessing (unchanged behavior, unchanged code).
"""

from __future__ import annotations

from typing import Any, Dict

GOOGLE_PLAY_PRODUCTS: Dict[str, Dict[str, Any]] = {
    "jyotishasha.silver.monthly": {
        "plan": "SILVER_MONTHLY",
        "base_plan_id": "monthly",
        "billing_cycle": "monthly",
        "section": "silver",
        "price_inr": 99,
    },
    "jyotishasha.silver.yearly": {
        "plan": "SILVER_YEARLY",
        "base_plan_id": "yearly",
        "billing_cycle": "yearly",
        "section": "silver",
        "price_inr": 990,
    },
    "jyotishasha.gold.monthly": {
        "plan": "GOLD_MONTHLY",
        # The original "monthly" base plan for this product is
        # inactive; "monthlyc" is the only currently sellable base
        # plan. Recorded here for reference only -- see this module's
        # own docstring for why base_plan_id never gates resolution.
        "base_plan_id": "monthlyc",
        "billing_cycle": "monthly",
        "section": "gold",
        "price_inr": 251,
    },
    "jyotishasha.gold.yearly": {
        "plan": "GOLD_YEARLY",
        "base_plan_id": "yearly",
        "billing_cycle": "yearly",
        "section": "gold",
        "price_inr": 2510,
    },
    "jyotishasha.platinum.yearly": {
        "plan": "PLATINUM_YEARLY",
        "base_plan_id": "yearly",
        "billing_cycle": "yearly",
        "section": "platinum",
        "price_inr": 3990,
    },
}

# The exact shape PaymentService and the RTDN dispatcher already
# expect from GOOGLE_PLAY_PRODUCT_TO_PLAN -- unchanged since S4, only
# now populated and centrally derived instead of hardcoded/empty.
GOOGLE_PLAY_PRODUCT_TO_PLAN: Dict[str, str] = {
    product_id: entry["plan"] for product_id, entry in GOOGLE_PLAY_PRODUCTS.items()
}


class GooglePlayProductConfigError(Exception):
    """Raised at import time (S16, S13 audit findings M-2/H-5) if this
    module's own configuration is internally inconsistent. Deliberately
    NOT caught anywhere -- an inconsistent config must fail the whole
    app startup rather than let a broken mapping silently reach a real,
    already-charged purchase (exactly the "unmapped by typo" scenario
    the S13 audit found: the product itself resolves, just to the
    wrong/nonexistent plan, so UNMAPPED_PRODUCT's own honest reporting
    never catches it)."""


def _validate_google_play_products() -> None:
    # Imported here, not at module top level, purely to keep this
    # file's own import graph minimal until validation actually runs;
    # neither import creates a cycle (both are low-level model/policy
    # modules with no dependency back on modules.payments or this file).
    from modules.entitlement.plan_access_policy import PLAN_SEGMENT_ACCESS
    from modules.models_premium_subscription import SUBSCRIPTION_PLANS

    product_ids = list(GOOGLE_PLAY_PRODUCTS.keys())
    if len(product_ids) != len(set(product_ids)):
        raise GooglePlayProductConfigError(
            "Duplicate Google Play product_id detected in GOOGLE_PLAY_PRODUCTS."
        )

    for product_id, entry in GOOGLE_PLAY_PRODUCTS.items():
        plan = entry.get("plan")
        if not plan:
            raise GooglePlayProductConfigError(
                f"GOOGLE_PLAY_PRODUCTS[{product_id!r}] has no 'plan' configured."
            )
        if plan not in SUBSCRIPTION_PLANS:
            raise GooglePlayProductConfigError(
                f"GOOGLE_PLAY_PRODUCTS[{product_id!r}] maps to plan {plan!r}, which "
                f"is not in SUBSCRIPTION_PLANS -- fix the typo/mismatch before this "
                f"can ever reach a real purchase."
            )
        if plan not in PLAN_SEGMENT_ACCESS:
            raise GooglePlayProductConfigError(
                f"Plan {plan!r} (from GOOGLE_PLAY_PRODUCTS[{product_id!r}]) has no "
                f"entry in PLAN_SEGMENT_ACCESS -- a successfully activated purchase "
                f"on this plan would silently grant zero accessible segments forever."
            )

        # base_plan_id is a single string in this config's current
        # shape (see module docstring) -- defensively also accept a
        # list, so "no duplicate base plan ids within the same
        # product" stays a real, checkable rule if this config is ever
        # extended to record more than one base plan per product.
        base_plan_id = entry.get("base_plan_id")
        if isinstance(base_plan_id, str):
            base_plan_ids = [base_plan_id] if base_plan_id else []
        elif isinstance(base_plan_id, (list, tuple)):
            base_plan_ids = list(base_plan_id)
        else:
            base_plan_ids = []
        if not base_plan_ids:
            raise GooglePlayProductConfigError(
                f"GOOGLE_PLAY_PRODUCTS[{product_id!r}] has no base_plan_id configured."
            )
        if len(base_plan_ids) != len(set(base_plan_ids)):
            raise GooglePlayProductConfigError(
                f"GOOGLE_PLAY_PRODUCTS[{product_id!r}] has a duplicate base_plan_id "
                f"within the same product: {base_plan_ids!r}."
            )

    # Every internal plan this codebase recognizes must resolve
    # somewhere sensible for segment access too -- SUBSCRIPTION_PLANS
    # is the single source of truth for "which plan names are valid at
    # all" (EntitlementWriteService's own rule); a plan with no
    # PLAN_SEGMENT_ACCESS entry would activate successfully and then
    # grant zero segments forever, with no error anywhere.
    missing_access = [plan for plan in SUBSCRIPTION_PLANS if plan not in PLAN_SEGMENT_ACCESS]
    if missing_access:
        raise GooglePlayProductConfigError(
            f"SUBSCRIPTION_PLANS contains plan(s) with no PLAN_SEGMENT_ACCESS entry: "
            f"{missing_access!r} -- add an ACCESS_ALL/ACCESS_SELECTED entry for "
            f"each before they can be sold."
        )


# Runs at import time -- the first import of this module (transitively,
# via modules/payments/payment_service.py, itself imported at
# app.py's own top level) fails the whole app startup if the
# configuration above is inconsistent. Never caught/suppressed
# anywhere in this codebase, by design -- see GooglePlayProductConfigError.
_validate_google_play_products()
